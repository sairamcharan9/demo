import os
import logging
import asyncio
import subprocess

logger = logging.getLogger("forge.agent")

async def clone_repo(repo_url: str, workspace: str, github_token: str | None = None):
    """Clone a git repo into the workspace directory.
    
    Ported from worker/main.py to make agent self-contained.
    """
    if os.path.isdir(os.path.join(workspace, ".git")):
        logger.info("Repo already cloned at %s — skipping clone", workspace)
        # Configure git identity inside the workspace even if already cloned
        for cmd in [
            ["git", "config", "user.email", "forge@agent.dev"],
            ["git", "config", "user.name", "Forge"],
        ]:
            try:
                await asyncio.to_thread(
                    subprocess.run,
                    cmd,
                    cwd=workspace,
                    capture_output=True,
                    check=True
                )
            except Exception:
                pass
        return

    # Inject token for private repos: https://<token>@github.com/...
    clone_url = repo_url
    if github_token and "github.com" in repo_url:
        clone_url = repo_url.replace(
            "https://github.com",
            f"https://{github_token}@github.com",
        )

    logger.info("Cloning %s into %s ...", repo_url, workspace)
    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            ["git", "clone", "--depth=1", clone_url, workspace],
            capture_output=True,
            timeout=300,
        )

        if proc.returncode != 0:
            err_msg = proc.stderr.decode()
            logger.error("git clone failed:\n%s", err_msg)
            raise RuntimeError(f"git clone failed: {err_msg.strip()}")

        # Configure git identity inside the workspace
        for cmd in [
            ["git", "config", "user.email", "forge@agent.dev"],
            ["git", "config", "user.name", "Forge"],
        ]:
            await asyncio.to_thread(
                subprocess.run,
                cmd,
                cwd=workspace,
                capture_output=True,
                check=True
            )

        logger.info("Clone complete.")
    except Exception as e:
        logger.error("Exception during clone_repo: %s", e)
        raise
