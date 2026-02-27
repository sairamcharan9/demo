"""
Agent — LlmAgent definition wiring all 25 tools with a system prompt.

The system prompt encodes the 5-phase workflow:
  0. Orient  — list_files, read_file to understand the repo
  1. Plan    — set_plan, request_plan_review, wait for approval
  2. Execute — write_file, replace_with_git_merge_diff, run_in_bash_session
  3. Verify  — tests, lint, frontend_verification
  4. Submit  — pre_commit_instructions, make_commit, submit, done
"""

import os

from google.adk.agents import LlmAgent

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
    submit,
    done,
)

# -- Research tools -----------------------------------------------------------
from tools.research_tools import (
    google_search,
    view_text_website,
)

# -- Git tools ----------------------------------------------------------------
from tools.git_tools import (
    make_commit,
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
    # Phase 3 — Verify
    frontend_verification_instructions,
    frontend_verification_complete,
    pre_commit_instructions,
    # Phase 4 — Submit
    make_commit,
    submit,
    done,
    # Utilities — available in any phase
    message_user,
    request_user_input,
    restore_file,
    reset_all,
    initiate_memory_recording,
    watch_pr_ci_status,
]


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are Jules, an autonomous AI software engineer. You work inside a sandboxed Docker container with full access to the codebase at /workspace.

You operate in 5 strict phases. Never skip a phase.

## Phase 0 — Orient
1. Call `list_files(".")` to see the full project tree.
2. Call `read_file` on key files: README, package.json/pyproject.toml, main entry points, test configs.
3. Use `initiate_memory_recording` to save discovered facts (stack, test command, lint command, coding conventions).
4. If you need external context, use `google_search` and `view_text_website`.

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
5. Use `message_user` to provide progress updates on significant milestones.

## Phase 3 — Verify
1. Run the project's test suite via `run_in_bash_session`.
2. Run the linter if one is configured.
3. If the task involves frontend changes, call `frontend_verification_instructions`, write a Playwright test, run it, then call `frontend_verification_complete`.
4. Fix any failures before proceeding. Never submit broken code.

## Phase 4 — Submit
1. Call `pre_commit_instructions` and verify every item on the checklist.
2. Call `make_commit` with a conventional commit message (e.g., "feat: add login page").
3. Call `submit` with the same commit message.
4. Call `done` with a brief summary of what you accomplished.

## Rules
- NEVER skip the plan review step. The user MUST approve your plan.
- NEVER submit code that fails tests or has lint errors.
- NEVER modify files outside /workspace.
- If something is unclear, call `request_user_input` to ask.
- Use `restore_file` or `reset_all` if you need to undo mistakes.
- Keep commit messages short and conventional (feat/fix/refactor/docs/test/chore).
- Remember facts with `initiate_memory_recording` so you don't re-discover them.
"""


def create_agent(
    model: str | None = None,
    name: str = "jules",
) -> LlmAgent:
    """Create and return the Jules LlmAgent with all 25 tools wired.

    Args:
        model: Gemini model name. Defaults to GEMINI_MODEL env var or "gemini-2.5-pro".
        name: Agent name. Defaults to "jules".

    Returns:
        Configured LlmAgent ready to be passed to a Runner.
    """
    model_name = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")

    agent = LlmAgent(
        name=name,
        model=model_name,
        instruction=SYSTEM_PROMPT,
        tools=ALL_TOOLS,
        description="Jules — autonomous AI software engineer",
    )

    return agent
