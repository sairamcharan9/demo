"""
Callbacks  -  ADK observability and guardrails for the Forge agent.

Contains:
   _infer_phase           -  infer workflow phase from session state
   clone_repo             -  async git clone used by before_agent_callback
   before_agent_callback  -  auto-reset workflow + auto-clone repo
   before_model_callback  -  log state snapshot before each LLM call
   before_tool_callback   -  capture state before tool execution
   after_tool_callback    -  log tool results and state changes after each tool call
   auto_save_session_to_memory_callback   -  save session to memory on completion/submission
"""

import os
import asyncio
import logging
import subprocess
from utils.workspace_utils import get_workspace

logger = logging.getLogger("forge.agent.callbacks")


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

    masked_url = clone_url
    if github_token:
        masked_url = clone_url.replace(github_token, "********")
        
    logger.info("Cloning into %s (URL: %s) ...", workspace, masked_url)
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

# Values that MUST exist for the SYSTEM_PROMPT template to resolve
MANDATORY_STATE_DEFAULTS = {
    "auto_approve": os.environ.get("AUTOMATION_MODE", "NONE"),
    "user:branch": os.environ.get("BRANCH", os.environ.get("branch", "main")).strip(),
    "approved": False,
    "plan": [],
    "current_step": 0,
    "completed_steps": [],
    "submitted": False,
    "task_complete": False,
    "current_branch": "main",
    "repo_url": os.environ.get("REPO_URL", ""),
}


async def before_agent_callback(callback_context):
    """Handle auto-reset and auto-clone before agent logic begins.

    State initialization is handled at session creation time in worker/main.py.
    This callback only handles:
    - Auto-reset workflow keys when a new task arrives after completion
    - Auto-clone the repo if configured
    - Logging the current state
    """
    state = callback_context.state
    user_content = callback_context.user_content
    user_id = callback_context.user_id

    # --- Seed missing mandatory variables (for adk run / adk web) ---
    for key, default_val in MANDATORY_STATE_DEFAULTS.items():
        # Check if key is missing or None (None means it was reset but needs a default)
        if key not in state or state[key] is None:
            # Copy mutable objects
            new_val = default_val.copy() if isinstance(default_val, list) else default_val
            state[key] = new_val
            logger.debug("Seeded/Restored mandatory state key '%s' with %s", key, new_val)

    # --- Dynamic Workspace Mapping ---
    # Check both prefixed and top-level repo_url keys
    repo_url = state.get("user:repo_url") or state.get("repo_url")
    is_git_user = bool(repo_url) or user_id.startswith(("http://", "https://", "git@"))
    clone_target = repo_url if repo_url else user_id
    
    if not is_git_user:
        logger.debug("Not a git user (%s) and no repo_url found. Skipping auto-clone.", user_id)

    # --- Auto-reset workflow if task was previously marked DONE and user sent a new message ---
    reset_notice = None
    if state.get("task_complete") and user_content:
        user_text = "".join(p.text for p in user_content.parts if p.text)
        if user_text.strip():
            logger.info("New user request detected after task completion ('%s'). Resetting workflow state.", user_text[:50])
            logger.debug("Keys to reset: %s", RESET_STATE_KEYS)
            for key in RESET_STATE_KEYS:
                default_val = RESET_DEFAULTS.get(key)
                new_val = default_val.copy() if isinstance(default_val, list) else default_val
                state[key] = new_val
                logger.debug("Reset state key '%s' to %s", key, new_val)

            # We previously returned reset_notice here, but that causes the ADK runner 
            # to end the turns immediately. Instead, we just reset the state and let 
            # the agent proceed. The prompt will naturally start from Phase 0.
            logger.info("Workflow reset complete. Agent will continue with Phase 0.")

    if hasattr(state, "to_dict"):
        logger.info("Before agent callback DONE. Session State: %s", state.to_dict())
    else:
        logger.info("Before agent callback DONE. State: %s", state)

    # --- Auto-clone repo if configured ---
    workspace = get_workspace(callback_context)
    github_token = os.environ.get("GITHUB_TOKEN", "")
    branch = state.get("user:branch", "main")
        
    if is_git_user and workspace:
        # Resolve branch safely
        branch = state.get("user:branch") or state.get("branch", "main")
        
        logger.info("[auto-clone] Target: %s | Workspace: %s | Branch: %s", clone_target, workspace, branch)
        
        try:
            # Create root dir if needed
            os.makedirs(os.path.dirname(workspace), exist_ok=True)
            
            # If the workspace exists but isn't a git repo, clean it up to avoid clone errors
            if os.path.exists(workspace) and not os.path.isdir(os.path.join(workspace, ".git")):
                logger.warning("[auto-clone] Workspace exists but is not a git repo. Cleaning up %s", workspace)
                import shutil
                await asyncio.to_thread(shutil.rmtree, workspace, ignore_errors=True)    
            os.makedirs(workspace, exist_ok=True)
            await clone_repo(clone_target, workspace, github_token, branch=branch)
        except Exception as e:
            logger.error("Auto-clone failed in before_agent_callback: %s", e)
    
    return None


async def before_model_callback(callback_context, llm_request, **kwargs):
    """Log a state snapshot and handle phase inference."""
    state = callback_context.state

    try:
        phase = _infer_phase(state)
        plan = state.get("plan", [])
        step = state.get("current_step", 0)

        # Log system instruction for debugging state injection
        config = getattr(llm_request, "config", None)
        si = getattr(config, "system_instruction", None) if config else None
        
        # if si:
        #     si_text = str(si)
        #     if hasattr(si, 'parts') and si.parts:
        #         si_text = "".join(p.text for p in si.parts if p.text)
            
        #     logger.info("[before_model] System Instruction Snippet (len=%d): %s...", len(si_text), si_text[:300])
            
        #     # Check for un-substituted keys, ignoring common JSON-like false positives in state variables like 'plan'
        #     import re
        #     all_matches = re.findall(r'{[^{}]*}', si_text)
        #     # Filter matches that look like dict items or are obviously not state variables
        #     matches = [m for m in all_matches if ':' not in m and ' ' not in m]
            
        #     if matches:
        #         logger.warning("[before_model] Warning: Likely un-substituted keys found in SI: %s", matches)
        #     elif all_matches:
        #         logger.debug("[before_model] Potential traces found in SI (ignored as false positives): %s", all_matches)
        # else:
        #     logger.debug("[before_model] No system instruction found in request config.")
            
    except Exception as exc:
        logger.debug("[before_model] logging failed: %s", exc)

    return None


async def after_model_callback(callback_context, llm_response, **kwargs):
    """Log the model's response for debugging."""
    try:
        if llm_response and llm_response.content:
            parts = llm_response.content.parts or []
            logger.info("[after_model] Response Parts: %d", len(parts))
            for i, part in enumerate(parts):
                p_text = getattr(part, "text", None)
                p_fc = getattr(part, "function_call", None)
                if p_text:
                    logger.info("  Part %d (text): %s...", i, p_text[:100])
                if p_fc:
                    logger.info("  Part %d (call): %s", i, p_fc.name)
        
        if hasattr(llm_response, "error_code") and llm_response.error_code:
            logger.warning("[after_model] Error: %s - %s", llm_response.error_code, getattr(llm_response, "error_message", ""))
            try:
                # Log the raw response dict if possible
                if hasattr(llm_response, "to_dict"):
                    logger.debug("[after_model] Raw Response Dict: %s", llm_response.to_dict())
                else:
                    logger.debug("[after_model] Raw Response Str: %s", str(llm_response))
            except Exception:
                pass
    except Exception as exc:
        logger.debug("[after_model] logging failed: %s", exc)
    return None


async def before_tool_callback(tool, args, tool_context, **kwargs):
    """Capture a snapshot of the state before the tool runs."""
    state = tool_context.state
    # Store a shallow copy in temp state to compare later
    # to_dict() returns a serializable dict.
    if hasattr(state, "to_dict"):
        state_dict = state.to_dict()
    else:
        state_dict = dict(state)
        
    # We use a key that won't collide with normal state
    try:
        state["temp:before_tool_state"] = state_dict
    except Exception as e:
        logger.debug("Failed to store temp state: %s", e)
    return None


async def after_tool_callback(tool, args, tool_context, tool_response, **kwargs):
    """Validate and log tool results and state changes after each tool call."""
    try:
        tool_name = getattr(tool, "name", getattr(tool, "__name__", str(tool)))
        result = tool_response if isinstance(tool_response, dict) else {}
        state = tool_context.state
        
        # 1. Log Tool Result
        if "error" in result:
            err_details = str(result["error"]) or "Unknown error (empty response)"
            logger.warning("[Tool Result] %s -> ERROR: %s", tool_name, err_details[:500])
        elif "status" in result:
            logger.info("[Tool Result] %s -> %s", tool_name, result["status"])
        else:
            logger.debug("[Tool Result] %s -> completed", tool_name)

        # 2. Track and Log State Changes
        before_state = state.get("temp:before_tool_state")
        if before_state:
            if hasattr(state, "to_dict"):
                after_state = state.to_dict()
            else:
                after_state = dict(state)
            
            # Remove the temp key from comparison
            if "temp:before_tool_state" in after_state:
                del after_state["temp:before_tool_state"]
            
            diff = {}
            for k, v in after_state.items():
                if k not in before_state or before_state[k] != v:
                    diff[k] = v
            
            if diff:
                # Filter out messages/typed_messages if they are too noisy, 
                # but user asked to log state changes, so let's show them concisely.
                logger.info("[State Changed] %s", diff)
            
            # Clean up temp state by setting to None (State doesn't support del/pop)
            try:
                state["temp:before_tool_state"] = None
            except Exception:
                pass

    except Exception as exc:
        logger.debug("[after_tool] tracking failed: %s", exc)

    return None


async def auto_save_session_to_memory_callback(callback_context):
    """Save session to memory if submission was successful."""
    state = callback_context.state
    # Check if task is marked complete or submitted in the session state
    if state.get("task_complete") or state.get("submitted"):
        logger.info("Task complete/submitted. Saving session to memory...")
        try:
            # Use the built-in ADK method to persist the session to memory
            await callback_context.add_session_to_memory()
            logger.info("Successfully added session to memory service.")
        except Exception as e:
            logger.error("Error auto-saving session to memory: %s", e)
    
    return None
