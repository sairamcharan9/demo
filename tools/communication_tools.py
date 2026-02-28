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

from google.adk.tools import ToolContext


WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT", "/workspace")


async def _run_git(args: list[str], cwd: str, timeout: int = 30) -> tuple[int, str, str]:
    """Run a git/gh command and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    return proc.returncode, stdout.decode().strip(), stderr.decode().strip()


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


async def submit(commit_message: str, tool_context: ToolContext, workspace: str | None = None) -> dict:
    """Submit the completed work by committing, pushing, and creating a PR.

    Performs the full git submission flow:
    1. ``git add -A`` — stage all changes
    2. ``git commit -m "<message>"`` — create the commit
    3. ``git push origin HEAD`` — push to remote
    4. ``gh pr create`` — open a PR (if not already on main/master)

    Verifies the plan is approved and all steps are complete before allowing
    submission. The agent should call ``pre_commit_instructions()`` and
    self-verify before calling this tool.
    """
    if not commit_message or not commit_message.strip():
        return {"error": "Commit message must not be empty"}

    # Check plan approval
    if not tool_context.state.get("approved", False):
        return {"error": "Cannot submit — plan has not been approved. Call request_plan_review() first."}

    # Check all steps complete
    plan = tool_context.state.get("plan", [])
    completed = tool_context.state.get("completed_steps", [])
    if plan and len(completed) < len(plan):
        remaining = len(plan) - len(completed)
        return {"error": f"Cannot submit — {remaining} plan step(s) still incomplete."}

    ws = workspace or WORKSPACE_ROOT

    try:
        # 1. Stage all changes
        rc, _, err = await _run_git(["git", "add", "-A"], ws)
        if rc != 0:
            return {"error": f"git add failed: {err}"}

        # 2. Commit
        rc, out, err = await _run_git(["git", "commit", "-m", commit_message], ws)
        if rc != 0:
            if "nothing to commit" in err or "nothing to commit" in out:
                return {"error": "Nothing to commit — working tree is clean."}
            return {"error": f"git commit failed: {err}"}

        # 3. Get commit SHA
        rc, sha, _ = await _run_git(["git", "rev-parse", "HEAD"], ws, timeout=10)

        # 4. Push to remote
        rc, out, err = await _run_git(
            ["git", "push", "origin", "HEAD"], ws, timeout=60
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

        # 5. Create PR via gh CLI
        pr_url = ""
        pr_number = 0
        rc, out, err = await _run_git(
            ["gh", "pr", "create", "--title", commit_message,
             "--body", f"Automated PR by Forge.\n\nCommit: {sha}"],
            ws, timeout=60,
        )
        if rc == 0:
            pr_url = out
            match = re.search(r"/pull/(\d+)", pr_url)
            if match:
                pr_number = int(match.group(1))

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
        result["message"] = "Work submitted and pushed. PR creation skipped or failed."

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


async def send_message_to_user(
    message: str, message_type: str = "progress", tool_context: ToolContext = None
) -> dict:
    """Send a typed status message to the user.

    Like ``message_user`` but includes a ``message_type`` field that maps to
    different AG-UI event severities in production:
    - "progress" — normal update (default)
    - "warning"  — something the user should be aware of
    - "error"    — a problem occurred

    Appends to ``typed_messages`` list in session state.
    """
    if not message or not message.strip():
        return {"error": "Message must not be empty"}

    valid_types = ("progress", "warning", "error")
    if message_type not in valid_types:
        return {"error": f"Invalid message_type '{message_type}'. Must be one of: {', '.join(valid_types)}"}

    if tool_context is not None:
        typed_messages = tool_context.state.get("typed_messages", [])
        typed_messages.append({"message": message, "type": message_type})
        tool_context.state["typed_messages"] = typed_messages

    return {
        "status": "ok",
        "message": message,
        "message_type": message_type,
    }


async def read_pr_comments(
    pr_number: int, tool_context: ToolContext = None, workspace: str | None = None
) -> dict:
    """Fetch comments on a GitHub PR using the ``gh`` CLI.

    Runs ``gh pr view <number> --comments --json comments`` and returns
    the parsed comment list with author, body, and createdAt fields.
    """
    if not isinstance(pr_number, int) or pr_number <= 0:
        return {"error": f"Invalid PR number: {pr_number}"}

    ws = workspace or WORKSPACE_ROOT

    try:
        proc = await asyncio.create_subprocess_exec(
            "gh", "pr", "view", str(pr_number),
            "--comments", "--json", "comments",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=ws,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        if proc.returncode != 0:
            return {"error": f"gh pr view failed: {stderr.decode().strip()}"}

    except FileNotFoundError:
        return {"error": "'gh' CLI not found on system. Install GitHub CLI."}
    except asyncio.TimeoutError:
        return {"error": "gh pr view timed out"}

    import json
    try:
        data = json.loads(stdout.decode())
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
    pr_number: int, body: str, tool_context: ToolContext = None, workspace: str | None = None
) -> dict:
    """Post a comment on a GitHub PR using the ``gh`` CLI.

    Runs ``gh pr comment <number> --body "<body>"``.
    """
    if not isinstance(pr_number, int) or pr_number <= 0:
        return {"error": f"Invalid PR number: {pr_number}"}

    if not body or not body.strip():
        return {"error": "Comment body must not be empty"}

    ws = workspace or WORKSPACE_ROOT

    try:
        proc = await asyncio.create_subprocess_exec(
            "gh", "pr", "comment", str(pr_number),
            "--body", body,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=ws,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        if proc.returncode != 0:
            return {"error": f"gh pr comment failed: {stderr.decode().strip()}"}

    except FileNotFoundError:
        return {"error": "'gh' CLI not found on system. Install GitHub CLI."}
    except asyncio.TimeoutError:
        return {"error": "gh pr comment timed out"}

    return {
        "status": "ok",
        "pr_number": pr_number,
        "body": body,
        "message": f"Comment posted on PR #{pr_number}.",
    }

