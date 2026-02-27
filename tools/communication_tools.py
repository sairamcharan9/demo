"""
Communication Tools — 4 tools for agent ↔ user communication.

These tools manage the agent's ability to send messages, ask questions,
and signal task completion. In production, they emit AG-UI events
(TEXT_MESSAGE_START, INTERRUPT, STATE_DELTA). In testing, they mutate
tool_context.state.

All tools are async for ADK parallelisation.
"""

import os
import asyncio


WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT", "/workspace")


async def message_user(message: str, tool_context) -> dict:
    """Send a status message to the user.

    Appends to ``messages`` list in session state. In production this
    emits an AG-UI TEXT_MESSAGE_START event that streams to the frontend.
    """
    if not message or not message.strip():
        return {"error": "Message must not be empty"}

    messages = tool_context.state.get("messages", [])
    messages.append(message)
    tool_context.state["messages"] = messages

    return {
        "status": "ok",
        "message": message,
        "total_messages": len(messages),
    }


async def request_user_input(prompt: str, tool_context) -> dict:
    """Ask the user a question and wait for their response.

    Sets ``awaiting_user_input`` to True and stores the prompt. In production
    this emits an AG-UI INTERRUPT event. The agent blocks until the user
    responds via the API.
    """
    if not prompt or not prompt.strip():
        return {"error": "Prompt must not be empty"}

    tool_context.state["awaiting_user_input"] = True
    tool_context.state["user_input_prompt"] = prompt

    return {
        "status": "awaiting_input",
        "prompt": prompt,
        "message": "Waiting for user response.",
    }


async def submit(commit_message: str, tool_context, workspace: str | None = None) -> dict:
    """Submit the completed work for review.

    Verifies the plan is approved and all steps are complete before allowing
    submission. Sets ``submitted`` to True. In production this triggers:
    1. ``git add -A && git commit``
    2. ``git push``
    3. PR creation via GitHub API

    The agent should call ``pre_commit_instructions()`` and self-verify
    before calling this tool.
    """
    if not commit_message or not commit_message.strip():
        return {"error": "Commit message must not be empty"}

    # Check plan approval
    if not tool_context.state.get("approved", False):
        return {"error": "Cannot submit — plan has not been approved. Call request_plan_review() first."}

    # Check all steps complete
    plan = tool_context.state.get("plan", [])
    completed = tool_context.state.get("completed_steps", [])
    if plan and len(completed) < len(plan):
        remaining = len(plan) - len(completed)
        return {"error": f"Cannot submit — {remaining} plan step(s) still incomplete."}

    # Record submission
    tool_context.state["submitted"] = True
    tool_context.state["commit_message"] = commit_message

    # In production, this would run git commit + push + PR creation.
    # For now, just record the intent.
    ws = workspace or WORKSPACE_ROOT

    return {
        "status": "ok",
        "commit_message": commit_message,
        "workspace": ws,
        "message": "Work submitted. PR creation will follow.",
    }


async def done(summary: str, tool_context) -> dict:
    """Signal that the task is complete.

    This is the terminal tool — the agent stops executing after calling this.
    Sets ``task_complete`` to True and records the final summary.
    In production this emits an AG-UI RUN_FINISHED event.
    """
    if not summary or not summary.strip():
        return {"error": "Summary must not be empty"}

    tool_context.state["task_complete"] = True
    tool_context.state["final_summary"] = summary

    return {
        "status": "ok",
        "summary": summary,
        "message": "Task marked as complete.",
    }
