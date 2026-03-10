"""
Agent — Multi-Agent System (MAS) definition for Forge.
"""

import os
import logging

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.tools.agent_tool import AgentTool

logger = logging.getLogger("forge.agent")

# Configure persistent file logging for debugging
_log_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "logs"))
os.makedirs(_log_dir, exist_ok=True)
_handler = logging.FileHandler(os.path.join(_log_dir, "forge.log"), mode="a", encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
logger.addHandler(_handler)
logger.setLevel(logging.DEBUG)

# -- Tools Imports ------------------------------------------------------------
from tools.file_tools import (
    list_files, read_file, write_file, replace_with_git_merge_diff,
    delete_file, rename_file, restore_file, reset_all
)
from tools.shell_tools import (
    run_in_bash_session, frontend_verification_instructions, frontend_verification_complete
)
from tools.planning_tools import (
    set_plan, plan_step_complete,
    record_user_approval_for_plan, pre_commit_instructions, initiate_memory_recording
)
from tools.communication_tools import (
    message_user, request_user_input, submit, done,
    read_pr_comments, reply_to_pr_comments
)
from tools.research_tools import (
    view_text_website, view_image, read_image_file
)
from tools.specialized_tools import (
    start_live_preview_instructions, call_hello_world_agent
)
from google.adk.tools.load_memory_tool import LoadMemoryTool
from google.adk.tools.preload_memory_tool import PreloadMemoryTool

# -- Callbacks ----------------------------------------------------------------
from app.callbacks import (
    before_agent_callback, before_model_callback, after_model_callback,
    before_tool_callback, after_tool_callback, auto_save_session_to_memory_callback
)

# -- Instructions -------------------------------------------------------------
from app.instructions import (
    PLANNER_INSTRUCTIONS, EXECUTOR_INSTRUCTIONS,
    VERIFIER_INSTRUCTIONS, SUBMITTER_INSTRUCTIONS, COORDINATOR_INSTRUCTIONS
)

# ---------------------------------------------------------------------------
# Specialized Agents
# ---------------------------------------------------------------------------

def create_specialized_agents(model_name: str):
    planner = LlmAgent(
        name="planner",
        model=model_name,
        instruction=PLANNER_INSTRUCTIONS,
        tools=[
            list_files, read_file, view_text_website, view_image,
            read_image_file, initiate_memory_recording, LoadMemoryTool(), PreloadMemoryTool(),
            set_plan, record_user_approval_for_plan, request_user_input,
            message_user
        ],
        description="Analyzes the codebase, creates and refines the execution plan",
    )

    executor = LlmAgent(
        name="executor",
        model=model_name,
        instruction=EXECUTOR_INSTRUCTIONS,
        tools=[
            read_file, write_file, replace_with_git_merge_diff, delete_file,
            rename_file, run_in_bash_session, plan_step_complete, message_user,
            record_user_approval_for_plan, request_user_input
        ],
        description="Implements the approved plan",
    )

    verifier = LlmAgent(
        name="verifier",
        model=model_name,
        instruction=VERIFIER_INSTRUCTIONS,
        tools=[
            run_in_bash_session, frontend_verification_instructions,
            frontend_verification_complete, message_user,
            record_user_approval_for_plan, request_user_input
        ],
        description="Verifies the changes through tests and review",
    )

    submitter = LlmAgent(
        name="submitter",
        model=model_name,
        instruction=SUBMITTER_INSTRUCTIONS,
        tools=[
            pre_commit_instructions, submit, done
        ],
        description="Finalizes and submits the work",
    )

    return planner, executor, verifier, submitter

def create_agent(
    model: str | None = None,
    name: str = "forge",
) -> LlmAgent:
    """Create the Forge Multi-Agent System."""
    model_name = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")

    planner, executor, verifier, submitter = create_specialized_agents(model_name)

    # Pipeline for the automated phases
    execution_pipeline = SequentialAgent(
        name="execution_pipeline",
        description="Implements, verifies, and submits the changes",
        sub_agents=[executor, verifier, submitter]
    )

    # Root coordinator agent
    coordinator = LlmAgent(
        name=name,
        model=model_name,
        instruction=COORDINATOR_INSTRUCTIONS,
        description="Forge — autonomous AI software engineering team coordinator",
        tools=[
            AgentTool(planner),
            AgentTool(execution_pipeline),
            # Root level might still need some basic communication tools
            message_user,
            request_user_input,
            done
        ],
        sub_agents=[execution_pipeline],
        before_agent_callback=before_agent_callback,
        before_model_callback=before_model_callback,
        after_model_callback=after_model_callback,
        before_tool_callback=before_tool_callback,
        after_tool_callback=after_tool_callback,
        after_agent_callback=auto_save_session_to_memory_callback,
        output_key="summary"
    )

    return coordinator

# Export root_agent for ADK CLI discovery
root_agent = create_agent()
