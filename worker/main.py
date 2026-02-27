"""
Worker — Docker container entry point.

1. Read env vars (REPO_URL, TASK, SESSION_ID, USER_ID, AUTOMATION_MODE)
2. Clone the repo into /workspace
3. Create session + memory services
4. Create the agent
5. Run the agent loop via ADK Runner
"""

import os
import sys
import asyncio
import logging

from google.adk.runners import Runner
from google.genai.types import Content, Part

# Add project root to path so tools/ and agent/ are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.agent import create_agent
from memory.vertex_memory import create_services


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("worker")


# ---------------------------------------------------------------------------
# Automation mode
# ---------------------------------------------------------------------------


AUTOMATION_MODES = {"NONE", "AUTO_APPROVE", "AUTO_CREATE_PR"}


# ---------------------------------------------------------------------------
# Git clone
# ---------------------------------------------------------------------------


async def clone_repo(repo_url: str, workspace: str, github_token: str | None = None):
    """Clone a git repo into the workspace directory.

    If a GitHub token is provided, it's injected into the clone URL for
    private repo access.
    """
    if os.path.isdir(os.path.join(workspace, ".git")):
        logger.info("Repo already cloned at %s — skipping clone", workspace)
        return

    # Inject token for private repos: https://<token>@github.com/...
    clone_url = repo_url
    if github_token and "github.com" in repo_url:
        clone_url = repo_url.replace(
            "https://github.com",
            f"https://{github_token}@github.com",
        )

    logger.info("Cloning %s into %s ...", repo_url, workspace)
    proc = await asyncio.create_subprocess_exec(
        "git", "clone", "--depth=1", clone_url, workspace,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

    if proc.returncode != 0:
        logger.error("git clone failed:\n%s", stderr.decode())
        raise RuntimeError(f"git clone failed: {stderr.decode().strip()}")

    # Configure git identity inside the workspace
    for cmd in [
        ["git", "config", "user.email", "jules@agent.dev"],
        ["git", "config", "user.name", "Jules"],
    ]:
        await asyncio.create_subprocess_exec(*cmd, cwd=workspace)

    logger.info("Clone complete.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run_worker():
    """Main worker loop: clone, create agent, run task."""

    # --- Read config from env ---
    repo_url = os.environ.get("REPO_URL")
    task = os.environ.get("TASK")
    session_id = os.environ.get("SESSION_ID", "default-session")
    user_id = os.environ.get("USER_ID", "default-user")
    github_token = os.environ.get("GITHUB_TOKEN")
    workspace = os.environ.get("WORKSPACE_ROOT", "/workspace")
    automation_mode = os.environ.get("AUTOMATION_MODE", "NONE")

    if automation_mode not in AUTOMATION_MODES:
        logger.warning(
            "Unknown AUTOMATION_MODE '%s', defaulting to NONE", automation_mode
        )
        automation_mode = "NONE"

    if not repo_url:
        logger.error("REPO_URL env var is required")
        sys.exit(1)
    if not task:
        logger.error("TASK env var is required")
        sys.exit(1)

    logger.info("=== Jules Worker Starting ===")
    logger.info("Repo:     %s", repo_url)
    logger.info("Task:     %s", task[:200])
    logger.info("Session:  %s", session_id)
    logger.info("User:     %s", user_id)
    logger.info("Mode:     %s", automation_mode)

    # --- Clone repo ---
    await clone_repo(repo_url, workspace, github_token)

    # --- Services ---
    session_service, memory_service = create_services()

    # --- Agent ---
    agent = create_agent()
    logger.info("Agent created: %s (model=%s)", agent.name, agent.model)

    # --- Runner ---
    runner = Runner(
        agent=agent,
        app_name="jules",
        session_service=session_service,
        memory_service=memory_service,
    )

    # --- Create session ---
    session = await session_service.create_session(
        app_name="jules",
        user_id=user_id,
        state={
            "automation_mode": automation_mode,
        },
    )
    logger.info("Session created: %s", session.id)

    # --- Inject auto-approval for AUTO_APPROVE / AUTO_CREATE_PR ---
    if automation_mode in ("AUTO_APPROVE", "AUTO_CREATE_PR"):
        task_with_mode = (
            f"{task}\n\n[SYSTEM: Automation mode is {automation_mode}. "
            f"Auto-approve the plan without waiting for user review.]"
        )
    else:
        task_with_mode = task

    # --- Run the agent ---
    logger.info("Starting agent loop...")
    user_message = Content(parts=[Part(text=task_with_mode)])

    async for event in runner.run_async(
        session_id=session.id,
        user_id=user_id,
        new_message=user_message,
    ):
        # Log events for observability
        if hasattr(event, "content") and event.content:
            for part in event.content.parts:
                if hasattr(part, "text") and part.text:
                    logger.info("[Agent] %s", part.text[:500])
                if hasattr(part, "function_call") and part.function_call:
                    logger.info(
                        "[Tool Call] %s(%s)",
                        part.function_call.name,
                        str(part.function_call.args)[:200],
                    )
                if hasattr(part, "function_response") and part.function_response:
                    logger.info(
                        "[Tool Result] %s → %s",
                        part.function_response.name,
                        str(part.function_response.response)[:200],
                    )

    logger.info("=== Jules Worker Complete ===")


def main():
    """Sync entry point for Docker CMD."""
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
