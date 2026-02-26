"""
Planning Tools — 6 tools for plan management and state tracking.

All state mutations go through tool_context.state[key] to ensure
they are persisted by VertexAiSessionService in production.

In testing, tool_context is a simple object with a `state` dict attribute.
"""


class MockToolContext:
    """Minimal stand-in for ADK ToolContext during testing."""

    def __init__(self, state: dict | None = None):
        self.state = state if state is not None else {}


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def set_plan(steps: list[str], tool_context) -> dict:
    """Write the execution plan to session state.

    Sets ``plan`` (list of step descriptions) and ``current_step`` to 0.
    Emits AG-UI STATE_DELTA in production.
    """
    if not steps:
        return {"error": "Plan must have at least one step"}

    tool_context.state["plan"] = steps
    tool_context.state["current_step"] = 0
    tool_context.state["completed_steps"] = []
    tool_context.state["approved"] = False

    return {
        "status": "ok",
        "total_steps": len(steps),
        "plan": steps,
    }


def plan_step_complete(step_index: int, summary: str, tool_context) -> dict:
    """Mark a plan step as complete and advance to the next one.

    Appends ``{step_index, summary}`` to ``completed_steps`` and
    increments ``current_step``. Emits AG-UI STATE_DELTA.
    """
    plan = tool_context.state.get("plan", [])
    if not plan:
        return {"error": "No plan set — call set_plan() first"}

    if step_index < 0 or step_index >= len(plan):
        return {"error": f"Invalid step index {step_index}. Plan has {len(plan)} steps."}

    completed = tool_context.state.get("completed_steps", [])
    completed.append({"step_index": step_index, "summary": summary})
    tool_context.state["completed_steps"] = completed

    next_step = step_index + 1
    if next_step < len(plan):
        tool_context.state["current_step"] = next_step
    else:
        tool_context.state["current_step"] = len(plan)  # all done

    return {
        "status": "ok",
        "completed_step": step_index,
        "summary": summary,
        "next_step": tool_context.state["current_step"],
        "total_completed": len(completed),
    }


def request_plan_review(tool_context) -> dict:
    """Pause the agent and request user approval for the current plan.

    Sets ``awaiting_approval`` to True. In production this emits an
    AG-UI INTERRUPT event. The agent blocks until ``approvePlan`` is called.
    """
    plan = tool_context.state.get("plan")
    if not plan:
        return {"error": "No plan to review — call set_plan() first"}

    tool_context.state["awaiting_approval"] = True

    return {
        "status": "awaiting_approval",
        "plan": plan,
        "message": "Plan submitted for review. Waiting for user approval.",
    }


def record_user_approval_for_plan(tool_context) -> dict:
    """Record that the user has approved the plan.

    Sets ``approved`` to True and clears ``awaiting_approval``.
    Emits AG-UI STATE_DELTA. Called by the API when user clicks Approve,
    or automatically in AUTO_CREATE_PR mode.
    """
    tool_context.state["approved"] = True
    tool_context.state["awaiting_approval"] = False

    return {
        "status": "ok",
        "approved": True,
        "message": "Plan approved. Proceeding with execution.",
    }


def pre_commit_instructions(tool_context=None) -> dict:
    """Return the pre-commit checklist the agent must complete before submit().

    This is a verification gate — the agent self-checks these items.
    """
    checklist = [
        "All planned steps are marked complete",
        "Tests pass (run test command from project)",
        "No linting errors (run linter if configured)",
        "git diff is clean — only intended changes remain",
        "No temporary files or debug code left behind",
        "Commit message accurately describes the change",
        "If frontend change: screenshot verification complete",
    ]

    return {
        "checklist": checklist,
        "instruction": "Complete ALL items before calling submit(). "
        "If any item fails, fix it before proceeding.",
    }


def initiate_memory_recording(key: str, value: str, tool_context) -> dict:
    """Write a user-scoped fact to session state.

    Keys are prefixed with ``user:`` so they persist across all sessions
    for this user. Used to remember discovered stack, test commands,
    and coding conventions.
    """
    if not key:
        return {"error": "Key must not be empty"}

    state_key = f"user:{key}" if not key.startswith("user:") else key
    tool_context.state[state_key] = value

    return {
        "status": "ok",
        "key": state_key,
        "value": value,
        "message": f"Memory recorded: {state_key}",
    }
