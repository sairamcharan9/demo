"""
Agent — LlmAgent definition wiring all 32 tools with a system prompt.

The system prompt encodes the 5-phase workflow:
  0. Orient  — list_files, read_file to understand the repo
  1. Plan    — set_plan, request_plan_review, wait for approval
  2. Execute — write_file, replace_with_git_merge_diff, run_in_bash_session
  3. Verify  — tests, lint, frontend_verification
  4. Submit  — pre_commit_instructions, make_commit, submit, done
"""

import os
import logging
import asyncio
import subprocess

from google.adk.agents import LlmAgent

logger = logging.getLogger("forge.agent")

# -- File tools ---------------------------------------------------------------
from tools.file_tools import (
    list_files,
    read_file,
    write_file,
    replace_with_git_merge_diff,
    delete_file,
    rename_file,
    restore_file,
    reset_all,
)

# -- Shell tools --------------------------------------------------------------
from tools.shell_tools import (
    run_in_bash_session,
    frontend_verification_instructions,
    frontend_verification_complete,
)

# -- Planning tools -----------------------------------------------------------
from tools.planning_tools import (
    set_plan,
    plan_step_complete,
    request_code_review,
    record_user_approval_for_plan,
    pre_commit_instructions,
    initiate_memory_recording,
)

# -- Communication tools ------------------------------------------------------
from tools.communication_tools import (
    message_user,
    request_user_input,
    submit,
    done,
    read_pr_comments,
    reply_to_pr_comments,
)

# -- Git tools ----------------------------------------------------------------
# (None currently)

# -- Research tools -----------------------------------------------------------
from tools.research_tools import (
    view_text_website,
    view_image,
    read_image_file,
)

# -- Specialized tools --------------------------------------------------------
from tools.specialized_tools import (
    start_live_preview_instructions,
    call_hello_world_agent,
)


# ---------------------------------------------------------------------------
# All tools — order matters for the model; group by workflow phase
# ---------------------------------------------------------------------------

ALL_TOOLS = [
    # File Management
    list_files,
    read_file,
    write_file,
    delete_file,
    rename_file,
    replace_with_git_merge_diff,
    restore_file,
    reset_all,

    # Shell Execution
    run_in_bash_session,

    # Information Retrieval
    view_text_website,
    view_image,
    read_image_file,

    # Planning & Workflow
    set_plan,
    plan_step_complete,
    initiate_memory_recording,
    pre_commit_instructions,
    submit,
    request_code_review,

    # Communication
    message_user,
    request_user_input,
    record_user_approval_for_plan,
    read_pr_comments,
    reply_to_pr_comments,

    # Specialized
    frontend_verification_instructions,
    frontend_verification_complete,
    start_live_preview_instructions,
    call_hello_world_agent,
    done,
]

# ---------------------------------------------------------------------------
# Callbacks — ADK §8 observability and guardrails
# ---------------------------------------------------------------------------


def _infer_phase(state: dict) -> str:
    """Infer the current workflow phase from session state."""
    if state.get("task_complete"):
        return "DONE"
    if state.get("submitted"):
        return "Phase 4 — Submit"
    plan = state.get("plan", [])
    if not plan:
        return "Phase 0 — Orient"
    if not state.get("approved"):
        return "Phase 1 — Plan"
    completed = state.get("completed_steps", [])
    if plan and len(completed) < len(plan):
        return "Phase 2 — Execute"
    return "Phase 3 — Verify"


async def before_agent_callback(callback_context):
    """Ensure required keys exist in session state before agent logic begins."""
    state = callback_context.state
    
    # Initialize missing keys to avoid prompt formatting errors
    # We pull from environment variables where available, mirroring worker/main.py login
    defaults = {
        "automation_mode": os.environ.get("AUTOMATION_MODE", "NONE"),
        "repo_url": os.environ.get("REPO_URL", ""),
        "task": os.environ.get("TASK", ""),
        "github_token": os.environ.get("GITHUB_TOKEN", ""),
        "workspace": os.environ.get("WORKSPACE_ROOT", "/workspace"),
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
    
    for key, val in defaults.items():
        if key not in state:
            state[key] = val

    # --- Auto-clone repo if it doesn't exist ---
    repo_url = state.get("repo_url")
    workspace = state.get("workspace")
    github_token = state.get("github_token")

    if repo_url and workspace:
        try:
            await clone_repo(repo_url, workspace, github_token)
        except Exception as e:
            logger.error("Auto-clone failed in before_agent_callback: %s", e)
            # We continue anyway, maybe tools will handle it or report error

    logger.info("Before agent callback DONE. Initialized state keys: %s", state)
    return None


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
                proc = await asyncio.create_subprocess_exec(*cmd, cwd=workspace)
                await proc.wait()
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
        proc = await asyncio.create_subprocess_exec(
            "git", "clone", "--depth=1", clone_url, workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

        if proc.returncode != 0:
            err_msg = stderr.decode()
            logger.error("git clone failed:\n%s", err_msg)
            raise RuntimeError(f"git clone failed: {err_msg.strip()}")

        # Configure git identity inside the workspace
        for cmd in [
            ["git", "config", "user.email", "forge@agent.dev"],
            ["git", "config", "user.name", "Forge"],
        ]:
            proc = await asyncio.create_subprocess_exec(*cmd, cwd=workspace)
            await proc.wait()

        logger.info("Clone complete.")
    except Exception as e:
        logger.error("Exception during clone_repo: %s", e)
        raise


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
            state.get("submitted", False),
        )
    except Exception as exc:
        logger.debug("[before_model] logging failed: %s", exc)

    # Return None to let the model proceed normally
    return None


async def after_tool_callback(tool, args, tool_context, tool_response, **kwargs):
    """Validate and log tool results after each tool call.

    ADK calls this as: callback(tool=..., args=..., tool_context=..., tool_response=...)
    """
    try:
        tool_name = getattr(tool, "name", getattr(tool, "__name__", str(tool)))
        result = tool_response if isinstance(tool_response, dict) else {}

        if "error" in result:
            logger.warning("[after_tool] %s → ERROR: %s", tool_name, str(result["error"])[:200])
        elif "status" in result:
            logger.info("[after_tool] %s → %s", tool_name, result["status"])
        else:
            logger.debug("[after_tool] %s → returned %d keys", tool_name, len(result))
    except Exception as exc:
        logger.debug("[after_tool] logging failed: %s", exc)

    # Return None to pass tool_response through unmodified
    return None


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are Forge, an autonomous AI software engineer. You work inside a sandboxed Docker container with full access to the codebase at /workspace.

## Current Session State
- Automation mode: {automation_mode?}
- Plan approved: {approved?}
- Plan steps: {plan?}
- Current step index: {current_step?}
- Completed steps: {completed_steps?}
- Submitted: {submitted?}
- Task complete: {task_complete?}
- Current branch: {current_branch?}

You operate in 5 strict phases. Never skip a phase.

## Phase 0 — Orient
1. Call `list_files(".")` to see the full project tree.
2. Call `read_file` on key files: README, package.json/pyproject.toml, main entry points, test configs.
3. Use `initiate_memory_recording` to save discovered facts (stack, test command, lint command, coding conventions).
4. If you need external context, use `google_search` and `view_text_website`.

6. Use `view_image` to inspect screenshots or diagrams in the repo.

## Phase 1 — Plan
1. Based on orientation, create a step-by-step execution plan using `set_plan`.
2. Each step should be atomic and testable.
3. Call `request_code_review` and STOP. Wait for user approval before proceeding.
4. Do NOT write any code until the plan is approved.

## Phase 2 — Execute
1. Work through the plan step by step. Call `plan_step_complete` after each step.
2. Prefer `replace_with_git_merge_diff` for edits to existing files — it produces clean diffs.
3. Use `write_file` only for new files or full rewrites.
4. Use `run_in_bash_session` to install dependencies, run intermediate checks, etc.
5. Use `message_user` to provide progress updates on significant milestones.

## Phase 3 — Verify
1. Run the project's test suite via `run_in_bash_session`.
2. Run the linter if one is configured.
3. If the task involves frontend changes, call `frontend_verification_instructions`, write a Playwright test, run it, then call `frontend_verification_complete`.
4. Fix any failures before proceeding. Never submit broken code.

## Phase 4 — Submit
1. Call `pre_commit_instructions` and verify every item on the checklist.
2. Call `submit` with a conventional commit message, a concise branch name, and a PR title.
3. Call `done` with a brief summary of what you accomplished.

## Rules
- NEVER skip the plan review step. The user MUST approve your plan.
- NEVER submit code that fails tests or has lint errors.
- NEVER modify files outside /workspace.
- If something is unclear, call `request_user_input` to ask.
- Use `restore_file` or `reset_all` if you need to undo mistakes.
- Keep commit messages short and conventional (feat/fix/refactor/docs/test/chore).
- Remember facts with `initiate_memory_recording` so you don't re-discover them.
- Use `read_pr_comments` and `reply_to_pr_comments` to interact with PR review feedback.
- Use `send_message_to_user` with type "warning" or "error" for important alerts.
"""


def create_agent(
    model: str | None = None,
    name: str = "forge",
) -> LlmAgent:
    """Create and return the Forge LlmAgent with all 32 tools wired.

    Args:
        model: Gemini model name. Defaults to GEMINI_MODEL env var or "gemini-2.5-pro".
        name: Agent name. Defaults to "forge".

    Returns:
        Configured LlmAgent ready to be passed to a Runner.
    """
    model_name = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")

    agent = LlmAgent(
        name=name,
        model=model_name,
        instruction=SYSTEM_PROMPT,
        tools=ALL_TOOLS,
        description="Forge — autonomous AI software engineer",
        before_agent_callback=before_agent_callback,
        before_model_callback=before_model_callback,
        after_tool_callback=after_tool_callback,
    )

    return agent

# Export root_agent for ADK CLI discovery
root_agent = create_agent()
