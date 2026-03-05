"""
Forge Worker — Docker container entry point.

1. Read env vars (REPO_URL, TASK, USER_ID, AUTOMATION_MODE)
2. Clone the repo into /workspace
3. Create an InMemoryRunner from the App (auto-creates services)
4. Run the agent loop via ADK Runner
"""

import os
import sys
import asyncio
import logging
import time
import argparse
import uuid

# Configure logging BEFORE any ADK imports — basicConfig is a no-op if root
# logger already has handlers, so it MUST come before imports that create loggers.
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("worker")

from dotenv import load_dotenv

# Load .env for local runs (no-op in Docker if .env doesn't exist)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from google.adk.runners import InMemoryRunner
from google.genai.types import Content, Part

# Add project root to path so tools/ and agent/ are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.agent import create_agent

# Enable ProactorEventLoop on Windows for async subprocesses
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from google.adk.apps import App, ResumabilityConfig

# ---------------------------------------------------------------------------
# ADK Web App Definition
# ---------------------------------------------------------------------------

# Wrap the agent in an App so 'adk web worker/main.py' finds it easily
app = App(
    name="forge",
    root_agent=create_agent(),
    resumability_config=ResumabilityConfig(is_resumable=True),
)


# ---------------------------------------------------------------------------
# Automation mode
# ---------------------------------------------------------------------------

AUTOMATION_MODES = {"NONE", "AUTO_APPROVE", "AUTO_CREATE_PR"}


# ---------------------------------------------------------------------------
# Initial session state — all keys seeded upfront at session creation
# ---------------------------------------------------------------------------

# User-level facts (persistent across sessions for the same user/repo)
USER_DEFAULTS = {
    "user:automation_mode": os.environ.get("AUTOMATION_MODE", "NONE"),
    "user:branch": os.environ.get("branch", os.environ.get("BRANCH", "main")).strip(),
    "user:stack": "",
    "user:test_command": "",
    "user:run_command": "",
}

# Session-level workflow state (scoped to current session)
SESSION_DEFAULTS = {
    "approved": False,
    "plan": [],
    "current_step": 0,
    "completed_steps": [],
    "submitted": False,
    "task_complete": False,
    "current_branch": "main",
    "awaiting_approval": False,
    "commit_message": "",
    "final_summary": "",
    "messages": [],
    "typed_messages": [],
    "awaiting_user_input": False,
    "user_input_prompt": "",
    "pr_url": "",
    "pr_number": 0,
}


def build_initial_state(repo_url: str, automation_mode: str) -> dict:
    """Build the full initial session state dict.

    Merges USER_DEFAULTS + SESSION_DEFAULTS + runtime config.
    List values are copied so each session gets its own mutable list.
    """
    state = {}
    for key, val in USER_DEFAULTS.items():
        state[key] = val
    for key, val in SESSION_DEFAULTS.items():
        state[key] = val.copy() if isinstance(val, list) else val
    # Runtime overrides
    state["repo_url"] = repo_url
    state["automation_mode"] = automation_mode
    state["user:automation_mode"] = automation_mode
    return state


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run_worker(task_arg: str | None = None, session_id_arg: str | None = None):
    """Main worker loop: create InMemoryRunner from App, run task."""

    # --- Read config from env ---
    repo_url = os.environ.get("REPO_URL")
    user_id = os.environ.get("USER_ID", "default-user")
    github_token = os.environ.get("GITHUB_TOKEN")
    workspace = os.environ.get("WORKSPACE_ROOT", "/workspace")
    automation_mode = os.environ.get("AUTOMATION_MODE", "NONE")

    # Session ID: arg > env > random uuid
    session_id = (
        session_id_arg or 
        os.environ.get("SESSION_ID") or 
        str(uuid.uuid4())
    )

    if automation_mode not in AUTOMATION_MODES:
        logger.warning(
            "Unknown AUTOMATION_MODE '%s', defaulting to NONE", automation_mode
        )
        automation_mode = "NONE"

    if not repo_url:
        logger.error("REPO_URL env var is required")
        sys.exit(1)

    logger.info("=== Forge Worker Starting ===")
    logger.info("Repo:     %s", repo_url)
    logger.info("Session:  %s", session_id)
    logger.info("User:     %s", user_id)
    logger.info("Mode:     %s", automation_mode)

    # --- Runner (dev mode) ---
    # InMemoryRunner auto-creates InMemorySessionService, InMemoryMemoryService,
    # and InMemoryArtifactService. Reuses the agent from the App object.
    runner = InMemoryRunner(app=app)
    logger.info("InMemoryRunner created from App (agent=%s)", app.root_agent.name)

    # --- Create or Resume Session ---
    try:
        session = await runner.session_service.get_session(
            app_name="forge",
            user_id=user_id,
            session_id=session_id
        )
        logger.info("Resuming existing session: %s", session.id)
    except Exception:
        # Create session with ALL state keys seeded upfront.
        initial_state = build_initial_state(repo_url, automation_mode)
        session = await runner.session_service.create_session(
            app_name="forge",
            user_id=user_id,
            session_id=session_id,
            state=initial_state,
        )
        logger.info("Created new session: %s (state keys: %d)", session.id, len(initial_state))

    # --- Inject auto-approval for AUTO_APPROVE / AUTO_CREATE_PR ---
    task = task_arg or os.environ.get("TASK", "")
    if automation_mode in ("AUTO_APPROVE", "AUTO_CREATE_PR"):
        task_with_mode = (
            f"{task}\n\n[SYSTEM: Automation mode is {automation_mode}. "
            f"Auto-approve the plan without waiting for user review.]"
        )
    else:
        task_with_mode = task

    # --- Run the agent (with retry for rate limits) ---
    logger.info("Starting agent loop...")
    user_message = Content(parts=[Part(text=task_with_mode)])

    max_retries = 5
    retry_delay = 15  # seconds, doubles each retry

    for attempt in range(max_retries + 1):
        try:
            async for event in runner.run_async(
                session_id=session.id,
                user_id=user_id,
                new_message=user_message,
            ):
                # Log events for observability
                if hasattr(event, "content") and event.content and event.content.parts:
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
                                "[Tool Result] %s \u2192 %s",
                                part.function_response.name,
                                str(part.function_response.response)[:200],
                            )
            # If we get here, the loop finished successfully
            break

        except Exception as exc:
            exc_str = str(exc).lower()
            is_rate_limit = (
                "429" in exc_str
                or "resource exhausted" in exc_str
                or "rate limit" in exc_str
                or "quota" in exc_str
                or "unavailable" in exc_str
                or "overloaded" in exc_str
                or "try again" in exc_str
            )
            if is_rate_limit and attempt < max_retries:
                wait = retry_delay * (2 ** attempt)
                logger.warning(
                    "Rate limited (attempt %d/%d). Retrying in %ds...",
                    attempt + 1, max_retries, wait,
                )
                await asyncio.sleep(wait)
                continue
            else:
                logger.error("Agent failed: %s", exc)
                raise

    logger.info("=== Forge Worker Complete ===")


def main():
    """Sync entry point for Docker CMD."""
    parser = argparse.ArgumentParser(description="Forge Agent Worker")
    parser.add_argument("task", nargs="?", default=None, help="Task description for the agent")
    parser.add_argument("--session-id", help="Session ID to resume")
    args = parser.parse_args()
    asyncio.run(run_worker(args.task, args.session_id))


if __name__ == "__main__":
    main()
