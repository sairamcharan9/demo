"""
Communication Tools — 7 tools for agent ↔ user communication and PR interaction.

These tools manage the agent's ability to send messages, ask questions,
signal task completion, and interact with GitHub PR comments. In production,
they emit AG-UI events (TEXT_MESSAGE_START, INTERRUPT, STATE_DELTA). In
testing, they mutate tool_context.state.

All tools are async for ADK parallelisation.
"""

import os
import re
import asyncio
import subprocess

from google.adk.tools import ToolContext
from utils.workspace_utils import get_workspace





async def _run_git(args: list[str], cwd: str, timeout: int = 30) -> tuple[int, str, str]:
    """Run a git/gh command and return (returncode, stdout, stderr)."""
    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout.decode().strip(), proc.stderr.decode().strip()
    except subprocess.TimeoutExpired:
        raise asyncio.TimeoutError(f"Command {' '.join(args)} timed out after {timeout}s")


async def message_user(message: str, tool_context: ToolContext) -> dict:
    """Send a status message to the user.

    Appends to ``messages`` list in session state. In production this
    emits an AG-UI TEXT_MESSAGE_START event that streams to the frontend.
    """
    if not message or not message.strip():
        return {"error": "Message must not be empty"}

    messages = tool_context.state.get("messages", [])
    messages.append(message)
    tool_context.state["messages"] = messages
    
    # Also append to typed_messages for UI stream visibility
    typed_messages = tool_context.state.get("typed_messages", [])
    typed_messages.append({"role": "assistant", "content": message})
    tool_context.state["typed_messages"] = typed_messages

    return {
        "status": "ok",
        "message": message,
        "total_messages": len(messages),
    }


async def request_user_input(prompt: str, tool_context: ToolContext) -> dict:
    """Ask the user a question and wait for their response.

    Sets ``awaiting_user_input`` to True and stores the prompt. In production
    this emits an AG-UI INTERRUPT event. The agent blocks until the user
    responds via the API.
    """
    if not prompt or not prompt.strip():
        return {"error": "Prompt must not be empty"}

    tool_context.state["awaiting_user_input"] = True
    tool_context.state["user_input_prompt"] = prompt

    return {
        "status": "awaiting_input",
        "prompt": prompt,
        "message": "Waiting for user response.",
    }


import uuid

async def submit(commit_message: str, branch_name: str, pr_title: str, tool_context: ToolContext, workspace: str = "") -> dict:
    """Submit the completed work by committing, pushing, and creating a PR.

    Performs the full git submission flow:
    1. ``git checkout -b <branch_name>-<session_id>``
    2. ``git add -A`` — stage all changes
    3. ``git commit -m "<message>"`` — create the commit
    4. ``git push -u origin <full_branch_name>`` — push to remote
    5. ``gh pr create`` — open a PR (if not already on main/master)

    Verifies the plan is approved and all steps are complete before allowing
    submission. The agent should call ``pre_commit_instructions()`` and
    self-verify before calling this tool.
    """
    if not commit_message or not commit_message.strip():
        return {"error": "Commit message must not be empty"}
    if not branch_name or not branch_name.strip():
        return {"error": "Branch name must not be empty"}
    if not pr_title or not pr_title.strip():
        return {"error": "PR title must not be empty"}

    # Check plan approval
    if not tool_context.state.get("approved", False):
        return {"error": "Cannot submit — plan has not been approved. Call record_user_approval_for_plan() first."}

    # Check all steps complete
    plan = tool_context.state.get("plan", [])
    completed = tool_context.state.get("completed_steps", [])
    if plan and len(completed) < len(plan):
        remaining = len(plan) - len(completed)
        return {"error": f"Cannot submit — {remaining} plan step(s) still incomplete."}

    ws = workspace or get_workspace(tool_context)
    
    # Get session ID safely
    session_id = getattr(tool_context, "session_id", None)
    if not session_id:
        session_id = uuid.uuid4().hex[:8]

    full_branch_name = tool_context.state.get("current_branch", False)
    # Construct full branch name safely removing invalid characters
    if not full_branch_name:
        clean_branch = re.sub(r'[^a-zA-Z0-9_-]', '-', branch_name)
        full_branch_name = f"{clean_branch}-{session_id}"
    try:
        # 1. Checkout new branch
        rc, _, err = await _run_git(["git", "checkout", "-b", full_branch_name], ws)
        if rc != 0:
            return {"error": f"git checkout -b failed: {err}"}
        
        # Update session state with the new branch name
        tool_context.state["current_branch"] = full_branch_name

        # 2. Stage all changes
        rc, _, err = await _run_git(["git", "add", "-A"], ws)
        if rc != 0:
            return {"error": f"git add failed: {err}"}

        # 3. Commit
        rc, out, err = await _run_git(["git", "commit", "-m", commit_message], ws)
        if rc != 0:
            if "nothing to commit" in err or "nothing to commit" in out:
                return {"error": "Nothing to commit — working tree is clean. Make changes before submitting."}
            return {"error": f"git commit failed: {err}"}

        # 4. Get commit SHA
        rc, sha, _ = await _run_git(["git", "rev-parse", "HEAD"], ws, timeout=10)

        # 5. Push to remote
        rc, out, err = await _run_git(
            ["git", "push", "-u", "origin", full_branch_name], ws, timeout=60
        )
        if rc != 0:
            # Push failed — still record the commit but report the push error
            tool_context.state["submitted"] = True
            tool_context.state["commit_message"] = commit_message
            return {
                "status": "partial",
                "sha": sha,
                "commit_message": commit_message,
                "push_error": err,
                "message": "Commit created but push failed. Check remote configuration.",
            }

        # 6. Create PR via gh CLI
        pr_url = ""
        pr_number = 0
        pr_error = ""
        rc, out, err = await _run_git(
            ["gh", "pr", "create", "--base", "main", "--head", full_branch_name, 
             "--title", pr_title, "--body", f"Automated PR by Forge.\n\nCommit: {sha}"],
            ws, timeout=60,
        )
        if rc == 0:
            pr_url = out
            match = re.search(r"/pull/(\d+)", pr_url)
            if match:
                pr_number = int(match.group(1))
        else:
            pr_error = err

        # 6. Reset workspace to main for the next task
        await _run_git(["git", "checkout", "main"], ws)
        await _run_git(["git", "pull", "origin", "main"], ws)

    except FileNotFoundError:
        return {"error": "git or gh CLI not found on system"}
    except asyncio.TimeoutError:
        return {"error": "git/gh command timed out during submission"}

    # Record submission in session state
    tool_context.state["submitted"] = True
    tool_context.state["commit_message"] = commit_message
    tool_context.state["pr_url"] = pr_url
    tool_context.state["pr_number"] = pr_number

    result = {
        "status": "ok",
        "sha": sha,
        "commit_message": commit_message,
        "workspace": ws,
    }
    if pr_url:
        result["pr_url"] = pr_url
        result["pr_number"] = pr_number
        result["message"] = f"Work submitted. PR created: {pr_url}"
    else:
        result["message"] = f"Work submitted and pushed. PR creation failed. git error: {pr_error}"

    return result


async def done(summary: str, tool_context: ToolContext) -> dict:
    """Signal that the task is complete.

    This is the terminal tool — the agent stops executing after calling this.
    Sets ``task_complete`` to True and records the final summary.
    Writes ``app:session_summary`` for ADK memory persistence.
    In production this emits an AG-UI RUN_FINISHED event.
    """
    if not summary or not summary.strip():
        return {"error": "Summary must not be empty"}

    tool_context.state["task_complete"] = True
    tool_context.state["final_summary"] = summary
    # app: prefix ensures this persists across sessions via ADK memory service
    tool_context.state["app:session_summary"] = summary

    return {
        "status": "ok",
        "summary": summary,
        "message": "Task marked as complete.",
    }



async def read_pr_comments(
    pr_number: int, tool_context: ToolContext = None, workspace: str = ""
) -> dict:
    """Fetch comments on a GitHub PR using the ``gh`` CLI.

    Runs ``gh pr view <number> --comments --json comments`` and returns
    the parsed comment list with author, body, and createdAt fields.
    """
    if not isinstance(pr_number, int) or pr_number <= 0:
        return {"error": f"Invalid PR number: {pr_number}"}

    ws = workspace or get_workspace(tool_context)

    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            ["gh", "pr", "view", str(pr_number), "--comments", "--json", "comments"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=ws,
            timeout=30,
        )

        if proc.returncode != 0:
            return {"error": f"gh pr view failed: {proc.stderr.decode().strip()}"}

        stdout_decoded = proc.stdout.decode()
    except FileNotFoundError:
        return {"error": "'gh' CLI not found on system. Install GitHub CLI."}
    except subprocess.TimeoutExpired:
        return {"error": "gh pr view timed out"}

    import json
    try:
        data = json.loads(stdout_decoded)
    except json.JSONDecodeError:
        return {"error": "Failed to parse gh output as JSON"}

    comments = []
    for comment in data.get("comments", []):
        comments.append({
            "author": comment.get("author", {}).get("login", "unknown"),
            "body": comment.get("body", ""),
            "createdAt": comment.get("createdAt", ""),
        })

    return {
        "status": "ok",
        "pr_number": pr_number,
        "comments": comments,
        "total_comments": len(comments),
    }


async def reply_to_pr_comments(
    pr_number: int, body: str, tool_context: ToolContext = None, workspace: str = ""
) -> dict:
    """Post a comment on a GitHub PR using the ``gh`` CLI.

    Runs ``gh pr comment <number> --body "<body>"``.
    """
    if not isinstance(pr_number, int) or pr_number <= 0:
        return {"error": f"Invalid PR number: {pr_number}"}

    if not body or not body.strip():
        return {"error": "Comment body must not be empty"}

    ws = workspace or get_workspace(tool_context)

    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            ["gh", "pr", "comment", str(pr_number), "--body", body],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=ws,
            timeout=30,
        )

        if proc.returncode != 0:
            return {"error": f"gh pr comment failed: {proc.stderr.decode().strip()}"}

    except FileNotFoundError:
        return {"error": "'gh' CLI not found on system. Install GitHub CLI."}
    except subprocess.TimeoutExpired:
        return {"error": "gh pr comment timed out"}

    return {
        "status": "ok",
        "pr_number": pr_number,
        "body": body,
        "message": f"Comment posted on PR #{pr_number}.",
    }

