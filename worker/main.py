"""
Forge Worker — Docker container entry point.

1. Read env vars (REPO_URL, TASK, USER_ID, AUTOMATION_MODE)
2. Clone the repo into /workspace
3. Create session + memory services
4. Create the agent
5. Run the agent loop via ADK Runner
"""

import os
import sys
import asyncio
import logging
import time
import argparse
import uuid

from dotenv import load_dotenv

# Load .env for local runs (no-op in Docker if .env doesn't exist)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

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
# Main
# ---------------------------------------------------------------------------


async def run_worker(task_arg: str | None = None, session_id_arg: str | None = None):
    """Main worker loop: clone, create agent, run task."""

    # --- Read config from env ---
    repo_url = os.environ.get("REPO_URL")
    task = task_arg or os.environ.get("TASK")
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
    if not task:
        logger.error("TASK env var is required")
        sys.exit(1)

    logger.info("=== Forge Worker Starting ===")
    logger.info("Repo:     %s", repo_url)
    logger.info("Task:     %s", task[:200])
    logger.info("Session:  %s", session_id)
    logger.info("User:     %s", user_id)
    logger.info("Mode:     %s", automation_mode)

    # --- Services ---
    session_service, memory_service = create_services()

    # --- Agent ---
    agent = create_agent()
    logger.info("Agent created: %s (model=%s)", agent.name, agent.model)

    # --- Runner ---
    runner = Runner(
        agent=agent,
        app_name="forge",
        session_service=session_service,
        memory_service=memory_service,
    )

    # --- Create or Resume Session ---
    try:
        session = await session_service.get_session(
            app_name="forge",
            user_id=user_id,
            session_id=session_id
        )
        logger.info("Resuming existing session: %s", session.id)
    except Exception:
        # Create session with minimal state. 
        # The before_agent_callback in agent.py will populate the rest.
        session = await session_service.create_session(
            app_name="forge",
            user_id=user_id,
            session_id=session_id,
            state={
                "repo_url": repo_url,
                "task": task,
                "automation_mode": automation_mode,
            },
        )
        logger.info("Created new session: %s", session.id)

    # --- Inject auto-approval for AUTO_APPROVE / AUTO_CREATE_PR ---
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
