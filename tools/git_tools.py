"""
Git Tools — 2 tools for git operations inside the workspace.

make_commit stages and commits all changes.
watch_pr_ci_status checks CI status for a PR via the GitHub CLI.

All tools are async for ADK parallelisation.
"""

import os
import asyncio


WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT", "/workspace")


async def make_commit(
    message: str, tool_context=None, workspace: str | None = None
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
    pr_number: int, tool_context=None, workspace: str | None = None
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
