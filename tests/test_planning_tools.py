"""Tests for tools/planning_tools.py — all 6 planning tools."""

import os
import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.planning_tools import (
    MockToolContext,
    set_plan,
    plan_step_complete,
    request_plan_review,
    record_user_approval_for_plan,
    pre_commit_instructions,
    initiate_memory_recording,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx():
    """Fresh MockToolContext with empty state."""
    return MockToolContext()


@pytest.fixture
def ctx_with_plan():
    """ToolContext that already has a plan set."""
    tc = MockToolContext()
    set_plan(["Step 1: Read code", "Step 2: Write code", "Step 3: Test"], tc)
    return tc


# ---------------------------------------------------------------------------
# set_plan
# ---------------------------------------------------------------------------


class TestSetPlan:
    def test_sets_plan(self, ctx):
        result = set_plan(["Do A", "Do B"], ctx)
        assert result["status"] == "ok"
        assert ctx.state["plan"] == ["Do A", "Do B"]
        assert ctx.state["current_step"] == 0
        assert ctx.state["completed_steps"] == []
        assert ctx.state["approved"] is False

    def test_total_steps(self, ctx):
        result = set_plan(["A", "B", "C"], ctx)
        assert result["total_steps"] == 3

    def test_empty_plan_rejected(self, ctx):
        result = set_plan([], ctx)
        assert "error" in result

    def test_overwrites_previous_plan(self, ctx):
        set_plan(["Old"], ctx)
        set_plan(["New A", "New B"], ctx)
        assert ctx.state["plan"] == ["New A", "New B"]
        assert ctx.state["current_step"] == 0


# ---------------------------------------------------------------------------
# plan_step_complete
# ---------------------------------------------------------------------------


class TestPlanStepComplete:
    def test_completes_first_step(self, ctx_with_plan):
        result = plan_step_complete(0, "Read all files", ctx_with_plan)
        assert result["status"] == "ok"
        assert result["completed_step"] == 0
        assert ctx_with_plan.state["current_step"] == 1
        assert len(ctx_with_plan.state["completed_steps"]) == 1

    def test_completes_all_steps(self, ctx_with_plan):
        plan_step_complete(0, "Done 0", ctx_with_plan)
        plan_step_complete(1, "Done 1", ctx_with_plan)
        result = plan_step_complete(2, "Done 2", ctx_with_plan)
        # current_step should be == len(plan) when all done
        assert ctx_with_plan.state["current_step"] == 3
        assert len(ctx_with_plan.state["completed_steps"]) == 3

    def test_invalid_step_index(self, ctx_with_plan):
        result = plan_step_complete(99, "nope", ctx_with_plan)
        assert "error" in result

    def test_negative_step_index(self, ctx_with_plan):
        result = plan_step_complete(-1, "nope", ctx_with_plan)
        assert "error" in result

    def test_no_plan_set(self, ctx):
        result = plan_step_complete(0, "nope", ctx)
        assert "error" in result

    def test_summary_recorded(self, ctx_with_plan):
        plan_step_complete(0, "Analyzed codebase", ctx_with_plan)
        assert ctx_with_plan.state["completed_steps"][0]["summary"] == "Analyzed codebase"


# ---------------------------------------------------------------------------
# request_plan_review
# ---------------------------------------------------------------------------


class TestRequestPlanReview:
    def test_sets_awaiting(self, ctx_with_plan):
        result = request_plan_review(ctx_with_plan)
        assert result["status"] == "awaiting_approval"
        assert ctx_with_plan.state["awaiting_approval"] is True

    def test_returns_plan(self, ctx_with_plan):
        result = request_plan_review(ctx_with_plan)
        assert result["plan"] == ctx_with_plan.state["plan"]

    def test_no_plan(self, ctx):
        result = request_plan_review(ctx)
        assert "error" in result


# ---------------------------------------------------------------------------
# record_user_approval_for_plan
# ---------------------------------------------------------------------------


class TestRecordUserApproval:
    def test_approves(self, ctx_with_plan):
        request_plan_review(ctx_with_plan)
        result = record_user_approval_for_plan(ctx_with_plan)
        assert result["approved"] is True
        assert ctx_with_plan.state["approved"] is True
        assert ctx_with_plan.state["awaiting_approval"] is False

    def test_approval_without_request(self, ctx_with_plan):
        # Should still work (AUTO_CREATE_PR mode skips request)
        result = record_user_approval_for_plan(ctx_with_plan)
        assert result["approved"] is True


# ---------------------------------------------------------------------------
# pre_commit_instructions
# ---------------------------------------------------------------------------


class TestPreCommitInstructions:
    def test_returns_checklist(self):
        result = pre_commit_instructions()
        assert "checklist" in result
        assert len(result["checklist"]) > 0

    def test_mentions_tests(self):
        result = pre_commit_instructions()
        checklists_str = " ".join(result["checklist"])
        assert "test" in checklists_str.lower()

    def test_mentions_lint(self):
        result = pre_commit_instructions()
        checklists_str = " ".join(result["checklist"])
        assert "lint" in checklists_str.lower()


# ---------------------------------------------------------------------------
# initiate_memory_recording
# ---------------------------------------------------------------------------


class TestInitiateMemoryRecording:
    def test_records_with_prefix(self, ctx):
        result = initiate_memory_recording("repo_stack", "Python + FastAPI", ctx)
        assert result["status"] == "ok"
        assert result["key"] == "user:repo_stack"
        assert ctx.state["user:repo_stack"] == "Python + FastAPI"

    def test_no_double_prefix(self, ctx):
        result = initiate_memory_recording("user:test_cmd", "pytest", ctx)
        assert result["key"] == "user:test_cmd"

    def test_empty_key_rejected(self, ctx):
        result = initiate_memory_recording("", "value", ctx)
        assert "error" in result

    def test_multiple_recordings(self, ctx):
        initiate_memory_recording("stack", "Node.js", ctx)
        initiate_memory_recording("test_cmd", "npm test", ctx)
        assert ctx.state["user:stack"] == "Node.js"
        assert ctx.state["user:test_cmd"] == "npm test"
