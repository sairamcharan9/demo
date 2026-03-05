"""
Agent — LlmAgent definition wiring all 32 tools with a system prompt.

The system prompt encodes the 5-phase workflow:
  0. Orient  — list_files, read_file to understand the repo
  1. Plan    — set_plan, record_user_approval_for_plan, wait for approval
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

# Configure persistent file logging for debugging
_log_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "logs"))
os.makedirs(_log_dir, exist_ok=True)
_handler = logging.FileHandler(os.path.join(_log_dir, "forge.log"), mode="a", encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
logger.addHandler(_handler)
logger.setLevel(logging.DEBUG)

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

# -- Memory tools -------------------------------------------------------------
from google.adk.tools.load_memory_tool import LoadMemoryTool
from google.adk.tools.preload_memory_tool import PreloadMemoryTool


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
    
    # Memory
    LoadMemoryTool(),
    PreloadMemoryTool(),
    
    done,
]

# ---------------------------------------------------------------------------
# Callbacks — imported from the canonical callbacks module
# ---------------------------------------------------------------------------

from agent.callbacks import (
    before_agent_callback,
    before_model_callback,
    after_model_callback,
    before_tool_callback,
    after_tool_callback,
    auto_save_session_to_memory_callback,
)


from agent.instructions import SYSTEM_PROMPT

# ------------------------------------------



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
        after_model_callback=after_model_callback,
        before_tool_callback=before_tool_callback,
        after_tool_callback=after_tool_callback,
        after_agent_callback=auto_save_session_to_memory_callback,
    )

    return agent

# Export root_agent for ADK CLI discovery
root_agent = create_agent()
