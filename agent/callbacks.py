"""
Callbacks  -  ADK observability and guardrails for the Forge agent.

Contains:
  _infer_phase           -  infer workflow phase from session state
  clone_repo             -  async git clone used by before_agent_callback
  before_agent_callback  -  auto-reset workflow + auto-clone repo
  before_model_callback  -  log state snapshot before each LLM call
  after_tool_callback    -  log tool results after each tool call
"""

import os
import asyncio
import logging
import subprocess
from utils.workspace_utils import get_workspace

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phase inference
# ---------------------------------------------------------------------------


def _infer_phase(state: dict) -> str:
    """Infer the current workflow phase from session state."""
    if state.get("task_complete"):
        return "DONE"
    if state.get("submitted"):
        return "Phase 4  -  Submit"
    plan = state.get("plan", [])
    if not plan:
        return "Phase 0  -  Orient"
    if not state.get("approved"):
        return "Phase 1  -  Plan"
    completed = state.get("completed_steps", [])
    if plan and len(completed) < len(plan):
        return "Phase 2  -  Execute"
    return "Phase 3  -  Verify"


# ---------------------------------------------------------------------------
# Git clone helper
# ---------------------------------------------------------------------------


async def clone_repo(repo_url: str, workspace: str, github_token: str | None = None, branch: str = "main"):
    """Clone a git repo into the workspace directory."""
    if os.path.isdir(os.path.join(workspace, ".git")):
        logger.info("Repo already cloned at %s  -  skipping clone", workspace)
        # Configure git identity inside the workspace even if already cloned
        for cmd in [
            ["git", "config", "user.email", "forge@agent.dev"],
            ["git", "config", "user.name", "Forge"],
        ]:
            try:
                await asyncio.to_thread(subprocess.run, cmd, cwd=workspace, check=True, capture_output=True)
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
            ["git", "clone", "--depth=1", "-b", branch, clone_url, workspace],
            capture_output=True,
            timeout=300
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
            await asyncio.to_thread(subprocess.run, cmd, cwd=workspace, check=True, capture_output=True)

        logger.info("Clone complete.")
    except Exception as e:
        logger.error("Exception during clone_repo: %s", e)
        raise


# ---------------------------------------------------------------------------
# ADK Callbacks
# ---------------------------------------------------------------------------


# Keys to reset when starting a new task in the same session
RESET_STATE_KEYS = [
    "task_complete", "plan", "current_step", "completed_steps",
    "submitted", "approved", "awaiting_approval", "final_summary",
    "awaiting_user_input", "user_input_prompt", "messages", "typed_messages"
]

# Default values for resetting (matches SESSION_DEFAULTS in worker/main.py)
RESET_DEFAULTS = {
    "task_complete": False,
    "plan": [],
    "current_step": 0,
    "completed_steps": [],
    "submitted": False,
    "approved": False,
    "awaiting_approval": False,
    "final_summary": "",
    "awaiting_user_input": False,
    "user_input_prompt": "",
    "messages": [],
    "typed_messages": [],
}


async def before_agent_callback(callback_context):
    """Handle auto-reset and auto-clone before agent logic begins.

    State initialization is handled at session creation time in worker/main.py.
    This callback only handles:
    - Auto-reset workflow keys when a new task arrives after completion
    - Auto-clone the repo if configured
    - Logging the current state
    """
    state = callback_context.session.state
    user_content = callback_context.user_content
    user_id = callback_context.user_id

    # --- Dynamic Workspace Mapping ---
    repo_url = state.get("user:repo_url")
    is_git_user = bool(repo_url) or user_id.startswith(("http://", "https://", "git@"))
    clone_target = repo_url if repo_url else user_id

    # --- Auto-reset workflow if task was previously marked DONE and user sent a new message ---
    reset_notice = None
    if state.get("task_complete") and user_content:
        user_text = "".join(p.text for p in user_content.parts if p.text)
        if user_text.strip():
            logger.info("New user request detected after task completion ('%s'). Resetting workflow state.", user_text[:50])
            for key in RESET_STATE_KEYS:
                default_val = RESET_DEFAULTS.get(key)
                state[key] = default_val.copy() if isinstance(default_val, list) else default_val

            from google.genai import types
            reset_notice = types.Content(
                role="user",
                parts=[types.Part(text="[SYSTEM] Previous task complete. Session state has been reset. Please handle the new user request starting from Phase 0 (Orient).")]
            )

    if hasattr(state, "to_dict"):
        logger.info("Before agent callback DONE. Session State: %s", state.to_dict())
    else:
        logger.info("Before agent callback DONE. State: %s", state)

    # --- Auto-clone repo if configured ---
    workspace = get_workspace(callback_context)
    github_token = os.environ.get("GITHUB_TOKEN", "")
    branch = state.get("user:branch", "main")

    if is_git_user and workspace:
        os.makedirs(workspace, exist_ok=True)
        try:
            await clone_repo(clone_target, workspace, github_token, branch=branch)
        except Exception as e:
            logger.error("Auto-clone failed in before_agent_callback for %s: %s", user_id, e)

    return reset_notice


async def before_model_callback(callback_context, llm_request, **kwargs):
    """Log a state snapshot and handle phase inference."""
    state = callback_context.state

    try:
        phase = _infer_phase(state)
        plan = state.get("plan", [])
        step = state.get("current_step", 0)

        logger.info(
            "[before_model] phase=%s step=%d/%d approved=%s submitted=%s",
            phase, step, len(plan),
            state.get("approved", False),
            state.get("submitted", False)
        )
    except Exception as exc:
        logger.debug("[before_model] logging failed: %s", exc)

    return None


async def after_tool_callback(tool, args, tool_context, tool_response, **kwargs):
    """Validate and log tool results after each tool call."""
    try:
        tool_name = getattr(tool, "name", getattr(tool, "__name__", str(tool)))
        result = tool_response if isinstance(tool_response, dict) else {}
        state = tool_context.state
        if hasattr(state, "to_dict"):
            logger.info("After tool callback. Session State: %s", state.to_dict())
        else:
            logger.info("After tool callback. State: %s", state)

        if "error" in result:
            err_details = str(result["error"]) or "Unknown error (empty response)"
            logger.warning("[after_tool] %s -> ERROR: %s", tool_name, err_details[:500])
        elif "status" in result:
            logger.info("[after_tool] %s -> %s", tool_name, result["status"])
        else:
            logger.debug("[after_tool] %s -> returned %d keys", tool_name, len(result))
    except Exception as exc:
        logger.debug("[after_tool] logging failed: %s", exc)

    return None
