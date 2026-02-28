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
    request_plan_review,
    record_user_approval_for_plan,
    pre_commit_instructions,
    initiate_memory_recording,
)

# -- Communication tools ------------------------------------------------------
from tools.communication_tools import (
    message_user,
    request_user_input,
    send_message_to_user,
    submit,
    done,
    read_pr_comments,
    reply_to_pr_comments,
)

# -- Research tools -----------------------------------------------------------
from tools.research_tools import (
    google_search,
    view_text_website,
    take_screenshot,
    view_image,
)

# -- Git tools ----------------------------------------------------------------
from tools.git_tools import (
    make_commit,
    create_branch,
    create_pr,
    watch_pr_ci_status,
)


# ---------------------------------------------------------------------------
# All tools — order matters for the model; group by workflow phase
# ---------------------------------------------------------------------------

ALL_TOOLS = [
    # Phase 0 — Orient
    list_files,
    read_file,
    # Phase 0-2 — Research
    google_search,
    view_text_website,
    take_screenshot,
    view_image,
    # Phase 1 — Plan
    set_plan,
    request_plan_review,
    record_user_approval_for_plan,
    plan_step_complete,
    # Phase 2 — Execute
    write_file,
    replace_with_git_merge_diff,
    delete_file,
    rename_file,
    run_in_bash_session,
    create_branch,
    # Phase 3 — Verify
    frontend_verification_instructions,
    frontend_verification_complete,
    pre_commit_instructions,
    # Phase 4 — Submit
    make_commit,
    create_pr,
    submit,
    done,
    # Utilities — available in any phase
    message_user,
    send_message_to_user,
    request_user_input,
    restore_file,
    reset_all,
    initiate_memory_recording,
    watch_pr_ci_status,
    read_pr_comments,
    reply_to_pr_comments,
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


async def before_model_callback(callback_context, llm_request, **kwargs):
    """Log a state snapshot before each LLM call.

    ADK calls this as: callback(callback_context=..., llm_request=...)
    callback_context.state gives access to session state.
    """
    try:
        state = callback_context.state
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
- Automation mode: {automation_mode}
- Plan approved: {approved}
- Plan steps: {plan}
- Current step index: {current_step}
- Completed steps: {completed_steps}
- Submitted: {submitted}
- Task complete: {task_complete}

You operate in 5 strict phases. Never skip a phase.

## Phase 0 — Orient
1. Call `list_files(".")` to see the full project tree.
2. Call `read_file` on key files: README, package.json/pyproject.toml, main entry points, test configs.
3. Use `initiate_memory_recording` to save discovered facts (stack, test command, lint command, coding conventions).
4. If you need external context, use `google_search` and `view_text_website`.
5. Use `take_screenshot` if you need to capture a webpage's visual state.
6. Use `view_image` to inspect screenshots or diagrams in the repo.

## Phase 1 — Plan
1. Based on orientation, create a step-by-step execution plan using `set_plan`.
2. Each step should be atomic and testable.
3. Call `request_plan_review` and STOP. Wait for user approval before proceeding.
4. Do NOT write any code until the plan is approved.

## Phase 2 — Execute
1. Work through the plan step by step. Call `plan_step_complete` after each step.
2. Prefer `replace_with_git_merge_diff` for edits to existing files — it produces clean diffs.
3. Use `write_file` only for new files or full rewrites.
4. Use `run_in_bash_session` to install dependencies, run intermediate checks, etc.
5. Use `message_user` or `send_message_to_user` to provide progress updates on significant milestones.
6. Use `create_branch` to work on a feature branch when appropriate.

## Phase 3 — Verify
1. Run the project's test suite via `run_in_bash_session`.
2. Run the linter if one is configured.
3. If the task involves frontend changes, call `frontend_verification_instructions`, write a Playwright test, run it, then call `frontend_verification_complete`.
4. Fix any failures before proceeding. Never submit broken code.

## Phase 4 — Submit
1. Call `pre_commit_instructions` and verify every item on the checklist.
2. Call `make_commit` with a conventional commit message (e.g., "feat: add login page").
3. Call `create_pr` if this is a feature branch that needs a PR.
4. Call `submit` with the same commit message.
5. Call `done` with a brief summary of what you accomplished.

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
        before_model_callback=before_model_callback,
        after_tool_callback=after_tool_callback,
    )

    return agent


