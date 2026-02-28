"""
Git Tools — 4 tools for git operations inside the workspace.

make_commit stages and commits all changes.
create_branch creates a new git branch.
create_pr creates a GitHub PR via the gh CLI.
watch_pr_ci_status checks CI status for a PR via the GitHub CLI.

All tools are async for ADK parallelisation.
"""

import os
import re
import asyncio

from google.adk.tools import ToolContext


WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT", "/workspace")


async def make_commit(
    message: str, tool_context: ToolContext = None, workspace: str | None = None
) -> dict:
    """Stage all changes and create a git commit.

    Runs ``git add -A`` followed by ``git commit -m "<message>"``.
    Returns the commit SHA on success.
    """
    if not message or not message.strip():
        return {"error": "Commit message must not be empty"}

    ws = workspace or WORKSPACE_ROOT

    try:
        # Stage all changes
        proc_add = await asyncio.create_subprocess_exec(
            "git", "add", "-A",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=ws,
        )
        _, stderr_add = await asyncio.wait_for(proc_add.communicate(), timeout=30)
        if proc_add.returncode != 0:
            return {"error": f"git add failed: {stderr_add.decode().strip()}"}

        # Commit
        proc_commit = await asyncio.create_subprocess_exec(
            "git", "commit", "-m", message,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=ws,
        )
        stdout_commit, stderr_commit = await asyncio.wait_for(
            proc_commit.communicate(), timeout=30
        )
        if proc_commit.returncode != 0:
            err = stderr_commit.decode().strip()
            # "nothing to commit" is not a real error
            if "nothing to commit" in err or "nothing to commit" in stdout_commit.decode():
                return {"error": "Nothing to commit — working tree is clean."}
            return {"error": f"git commit failed: {err}"}

        # Get the commit SHA
        proc_sha = await asyncio.create_subprocess_exec(
            "git", "rev-parse", "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=ws,
        )
        stdout_sha, _ = await asyncio.wait_for(proc_sha.communicate(), timeout=10)
        sha = stdout_sha.decode().strip()

    except FileNotFoundError:
        return {"error": "git not found on system"}
    except asyncio.TimeoutError:
        return {"error": "git command timed out"}

    return {
        "status": "ok",
        "sha": sha,
        "message": message,
    }


async def watch_pr_ci_status(
    pr_number: int, tool_context: ToolContext = None, workspace: str | None = None
) -> dict:
    """Check CI status for a GitHub PR using the ``gh`` CLI.

    Runs ``gh pr checks <number>`` and parses the output.
    Requires the ``gh`` CLI to be installed and authenticated.
    """
    if not isinstance(pr_number, int) or pr_number <= 0:
        return {"error": f"Invalid PR number: {pr_number}"}

    ws = workspace or WORKSPACE_ROOT

    try:
        proc = await asyncio.create_subprocess_exec(
            "gh", "pr", "checks", str(pr_number),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=ws,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        stdout_text = stdout.decode().strip()
        stderr_text = stderr.decode().strip()

        if proc.returncode != 0 and "no checks" not in stderr_text.lower():
            return {"error": f"gh pr checks failed: {stderr_text}"}

    except FileNotFoundError:
        return {"error": "'gh' CLI not found on system. Install GitHub CLI."}
    except asyncio.TimeoutError:
        return {"error": "gh pr checks timed out"}

    # Parse output lines — each line is: NAME\tSTATUS\tELAPSED\tURL
    checks = []
    all_pass = True
    for line in stdout_text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            check = {
                "name": parts[0].strip(),
                "status": parts[1].strip(),
            }
            if len(parts) >= 3:
                check["elapsed"] = parts[2].strip()
            if len(parts) >= 4:
                check["url"] = parts[3].strip()
            checks.append(check)
            if check["status"].lower() not in ("pass", "success"):
                all_pass = False

    overall = "pass" if all_pass and checks else "pending" if not checks else "failing"

    return {
        "status": overall,
        "pr_number": pr_number,
        "checks": checks,
        "total_checks": len(checks),
    }


# Valid git branch name pattern (simplified)
_BRANCH_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._\-/]*$")


async def create_branch(
    branch_name: str, tool_context: ToolContext = None, workspace: str | None = None
) -> dict:
    """Create and switch to a new git branch.

    Runs ``git checkout -b <branch_name>``. Validates the branch name format
    to prevent shell injection and invalid git refs.
    """
    if not branch_name or not branch_name.strip():
        return {"error": "Branch name must not be empty"}

    if not _BRANCH_NAME_RE.match(branch_name):
        return {
            "error": f"Invalid branch name '{branch_name}'. "
            "Use only letters, numbers, dots, hyphens, underscores, and forward slashes."
        }

    if ".." in branch_name or branch_name.endswith("/") or branch_name.endswith(".lock"):
        return {"error": f"Invalid branch name '{branch_name}'. Contains forbidden patterns."}

    ws = workspace or WORKSPACE_ROOT

    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "checkout", "-b", branch_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=ws,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        if proc.returncode != 0:
            err = stderr.decode().strip()
            if "already exists" in err:
                return {"error": f"Branch '{branch_name}' already exists."}
            return {"error": f"git checkout -b failed: {err}"}

    except FileNotFoundError:
        return {"error": "git not found on system"}
    except asyncio.TimeoutError:
        return {"error": "git command timed out"}

    return {
        "status": "ok",
        "branch": branch_name,
        "message": f"Switched to new branch '{branch_name}'.",
    }


async def create_pr(
    title: str,
    body: str = "",
    branch: str | None = None,
    tool_context: ToolContext = None,
    workspace: str | None = None,
) -> dict:
    """Create a GitHub PR using the ``gh`` CLI.

    Runs ``gh pr create --title <title> --body <body>``. If ``branch`` is
    provided it is passed as ``--head <branch>``.
    Requires the ``gh`` CLI to be installed and authenticated.
    """
    if not title or not title.strip():
        return {"error": "PR title must not be empty"}

    ws = workspace or WORKSPACE_ROOT

    cmd = ["gh", "pr", "create", "--title", title, "--body", body or ""]
    if branch:
        cmd.extend(["--head", branch])

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=ws,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)

        stdout_text = stdout.decode().strip()
        stderr_text = stderr.decode().strip()

        if proc.returncode != 0:
            return {"error": f"gh pr create failed: {stderr_text}"}

    except FileNotFoundError:
        return {"error": "'gh' CLI not found on system. Install GitHub CLI."}
    except asyncio.TimeoutError:
        return {"error": "gh pr create timed out"}

    # gh pr create outputs the PR URL on success
    pr_url = stdout_text

    # Try to extract PR number from URL
    pr_number = None
    match = re.search(r"/pull/(\d+)", pr_url)
    if match:
        pr_number = int(match.group(1))

    return {
        "status": "ok",
        "pr_url": pr_url,
        "pr_number": pr_number,
        "title": title,
        "message": f"PR created: {pr_url}",
    }

