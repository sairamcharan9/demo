"""Tests for tools/communication_tools.py — all 4 communication tools (async)."""

import os

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.planning_tools import (
    MockToolContext,
    set_plan,
    plan_step_complete,
    record_user_approval_for_plan,
)
from tools.communication_tools import (
    message_user,
    request_user_input,
    submit,
    done,
)

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx():
    """Fresh MockToolContext with empty state."""
    return MockToolContext()


@pytest.fixture
async def ctx_approved():
    """ToolContext with an approved, fully-completed plan."""
    tc = MockToolContext()
    await set_plan(["Step 1", "Step 2"], tc)
    await record_user_approval_for_plan(tc)
    await plan_step_complete(0, "Done 0", tc)
    await plan_step_complete(1, "Done 1", tc)
    return tc


# ---------------------------------------------------------------------------
# message_user
# ---------------------------------------------------------------------------


class TestMessageUser:
    async def test_sends_message(self, ctx):
        result = await message_user("Hello from agent", ctx)
        assert result["status"] == "ok"
        assert result["message"] == "Hello from agent"
        assert ctx.state["messages"] == ["Hello from agent"]

    async def test_accumulates_messages(self, ctx):
        await message_user("First", ctx)
        await message_user("Second", ctx)
        assert len(ctx.state["messages"]) == 2
        assert ctx.state["messages"][1] == "Second"

    async def test_total_count(self, ctx):
        await message_user("A", ctx)
        result = await message_user("B", ctx)
        assert result["total_messages"] == 2

    async def test_empty_message_rejected(self, ctx):
        result = await message_user("", ctx)
        assert "error" in result

    async def test_whitespace_only_rejected(self, ctx):
        result = await message_user("   ", ctx)
        assert "error" in result


# ---------------------------------------------------------------------------
# request_user_input
# ---------------------------------------------------------------------------


class TestRequestUserInput:
    async def test_sets_awaiting(self, ctx):
        result = await request_user_input("What branch?", ctx)
        assert result["status"] == "awaiting_input"
        assert ctx.state["awaiting_user_input"] is True
        assert ctx.state["user_input_prompt"] == "What branch?"

    async def test_empty_prompt_rejected(self, ctx):
        result = await request_user_input("", ctx)
        assert "error" in result


# ---------------------------------------------------------------------------
# submit
# ---------------------------------------------------------------------------


class TestSubmit:
    async def test_submits_when_ready(self, ctx_approved):
        result = await submit("Fix: resolve login bug", ctx_approved)
        assert result["status"] == "ok"
        assert ctx_approved.state["submitted"] is True
        assert ctx_approved.state["commit_message"] == "Fix: resolve login bug"

    async def test_rejects_without_approval(self, ctx):
        await set_plan(["Step 1"], ctx)
        result = await submit("msg", ctx)
        assert "error" in result
        assert "approved" in result["error"].lower() or "plan" in result["error"].lower()

    async def test_rejects_incomplete_steps(self):
        tc = MockToolContext()
        await set_plan(["Step 1", "Step 2"], tc)
        await record_user_approval_for_plan(tc)
        await plan_step_complete(0, "Done 0", tc)
        # Step 1 still incomplete
        result = await submit("msg", tc)
        assert "error" in result
        assert "incomplete" in result["error"].lower()

    async def test_empty_commit_message_rejected(self, ctx_approved):
        result = await submit("", ctx_approved)
        assert "error" in result

    async def test_stores_commit_message(self, ctx_approved):
        await submit("feat: add auth", ctx_approved)
        assert ctx_approved.state["commit_message"] == "feat: add auth"


# ---------------------------------------------------------------------------
# done
# ---------------------------------------------------------------------------


class TestDone:
    async def test_marks_complete(self, ctx):
        result = await done("Task finished successfully", ctx)
        assert result["status"] == "ok"
        assert ctx.state["task_complete"] is True
        assert ctx.state["final_summary"] == "Task finished successfully"

    async def test_empty_summary_rejected(self, ctx):
        result = await done("", ctx)
        assert "error" in result

    async def test_whitespace_only_rejected(self, ctx):
        result = await done("  \n ", ctx)
        assert "error" in result
