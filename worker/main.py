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
    level=logging.INFO,
    format="%(asctime)s [%(levelname).1s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("worker")

from dotenv import load_dotenv

# Load .env for local runs (no-op in Docker if .env doesn't exist)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from google.adk.runners import InMemoryRunner
from google.genai.types import Content, Part\

# Add project root to path so tools/ and agent/ are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.agent import create_agent

# Enable ProactorEventLoop on Windows for async subprocesses
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from google.adk.apps import App, ResumabilityConfig
from google.adk.agents.context_cache_config import ContextCacheConfig

# ---------------------------------------------------------------------------
# ADK Web App Definition
# ---------------------------------------------------------------------------

# Wrap the agent in an App so 'adk web worker/main.py' finds it easily
app = App(
    name="forge",
    root_agent=create_agent(),
    context_cache_config=ContextCacheConfig(
        min_tokens=2048,    # Minimum tokens to trigger caching
        ttl_seconds=600,    # Store for up to 10 minutes
        cache_intervals=5,  # Refresh after 5 uses
    ),
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
    "auto_approve": os.environ.get("AUTOMATION_MODE", "NONE"),
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
    state["auto_approve"] = automation_mode
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
                # 1. Log Basic Event Info
                is_final = event.is_final_response()
                actions = getattr(event, 'actions', None)
                end_of_agent = getattr(actions, 'end_of_agent', False) if actions else False
                
                parts = []
                if event.content and hasattr(event.content, "parts") and event.content.parts:
                    parts = event.content.parts
                elif isinstance(event.content, dict) and "parts" in event.content:
                    parts = event.content["parts"]
                    
                calls = event.get_function_calls()
                resps = event.get_function_responses()
                
                err_code = getattr(event, 'error_code', None)
                err_msg = getattr(event, 'error_message', None)
                
                logger.info(
                    "[Event] author=%-10s | final=%-5s | parts=%d | calls=%d | resps=%d | err=%s",
                    event.author, str(is_final), len(parts), len(calls), len(resps), str(err_code)
                )
                if err_msg:
                    logger.warning(" \u26a0\ufe0f  [Event Error] %s", err_msg)

                # 2. Extract and Log Parts (Text, Tool Calls, Tool Results)
                for part in parts:
                    # Normalize part access (object or dict)
                    p_text = getattr(part, "text", None) or (part.get("text") if isinstance(part, dict) else None)
                    p_fc = getattr(part, "function_call", None) or (part.get("function_call") if isinstance(part, dict) else None)
                    p_fr = getattr(part, "function_response", None) or (part.get("function_response") if isinstance(part, dict) else None)

                    if p_text and p_text.strip():
                        logger.info("\u2728 [Agent] %s", p_text.strip())
                    
                    if p_fc:
                        fc_name = getattr(p_fc, "name", None) or (p_fc.get("name") if isinstance(p_fc, dict) else None)
                        fc_args = getattr(p_fc, "args", None) or (p_fc.get("args") if isinstance(p_fc, dict) else None)
                        logger.info("\ud83d\udee0\ufe0f  [Tool Call] %s(%s)", fc_name, str(fc_args)[:200])
                    
                    if p_fr:
                        fr_name = getattr(p_fr, "name", None) or (p_fr.get("name") if isinstance(p_fr, dict) else None)
                        fr_resp = getattr(p_fr, "response", None) or (p_fr.get("response") if isinstance(p_fr, dict) else None)
                        status = "OK"
                        if isinstance(fr_resp, dict) and "error" in fr_resp:
                            status = f"ERROR: {str(fr_resp['error'])[:100]}"
                        logger.info("\u2705 [Tool Result] %s \u2192 %s", fr_name, status)

                # 3. Log State Changes if present in actions
                if actions and hasattr(actions, "state_delta") and actions.state_delta:
                    logger.info("[State Delta] %s", actions.state_delta)

                if end_of_agent:
                    logger.debug("End of agent signal received.")
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
