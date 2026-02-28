"""Tests for tools/communication_tools.py — all 7 communication tools (async)."""

import os

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import AsyncMock, patch

from tools.planning_tools import (
    set_plan,
    plan_step_complete,
    record_user_approval_for_plan,
)
from tests.conftest import MockToolContext
from tools.communication_tools import (
    message_user,
    request_user_input,
    send_message_to_user,
    submit,
    done,
    read_pr_comments,
    reply_to_pr_comments,
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
    @patch("tools.communication_tools._run_git")
    async def test_submits_when_ready(self, mock_run_git, ctx_approved):
        # Mock: git add, git commit, git rev-parse, git push, gh pr create
        mock_run_git.side_effect = [
            (0, "", ""),                          # git add
            (0, "commit ok", ""),                  # git commit
            (0, "abc123def456" * 3 + "abcd", ""),  # git rev-parse (40 chars)
            (0, "", ""),                          # git push
            (0, "https://github.com/org/repo/pull/42", ""),  # gh pr create
        ]
        result = await submit("feat: login", ctx_approved)
        assert result["status"] == "ok"
        assert ctx_approved.state["submitted"] is True
        assert ctx_approved.state["commit_message"] == "feat: login"
        assert ctx_approved.state["pr_url"] == "https://github.com/org/repo/pull/42"
        assert ctx_approved.state["pr_number"] == 42

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

    @patch("tools.communication_tools._run_git")
    async def test_push_failure_returns_partial(self, mock_run_git, ctx_approved):
        mock_run_git.side_effect = [
            (0, "", ""),                  # git add
            (0, "ok", ""),                # git commit
            (0, "abc" * 13 + "a", ""),    # git rev-parse
            (1, "", "no remote configured"),  # git push fails
        ]
        result = await submit("feat: test", ctx_approved)
        assert result["status"] == "partial"
        assert "push_error" in result
        assert ctx_approved.state["submitted"] is True

    @patch("tools.communication_tools._run_git")
    async def test_nothing_to_commit(self, mock_run_git, ctx_approved):
        mock_run_git.side_effect = [
            (0, "", ""),                              # git add
            (1, "", "nothing to commit, working tree clean"),  # git commit
        ]
        result = await submit("msg", ctx_approved)
        assert "error" in result
        assert "nothing to commit" in result["error"].lower()

    @patch("tools.communication_tools._run_git")
    async def test_stores_state_fields(self, mock_run_git, ctx_approved):
        mock_run_git.side_effect = [
            (0, "", ""),
            (0, "ok", ""),
            (0, "deadbeef" * 5, ""),
            (0, "", ""),
            (0, "https://github.com/org/repo/pull/7", ""),
        ]
        await submit("feat: add auth", ctx_approved)
        assert ctx_approved.state["commit_message"] == "feat: add auth"
        assert ctx_approved.state["pr_number"] == 7


# ---------------------------------------------------------------------------
# done
# ---------------------------------------------------------------------------


class TestDone:
    async def test_marks_complete(self, ctx):
        result = await done("Task finished successfully", ctx)
        assert result["status"] == "ok"
        assert ctx.state["task_complete"] is True
        assert ctx.state["final_summary"] == "Task finished successfully"

    async def test_writes_app_session_summary(self, ctx):
        await done("Completed the login feature", ctx)
        assert ctx.state["app:session_summary"] == "Completed the login feature"

    async def test_empty_summary_rejected(self, ctx):
        result = await done("", ctx)
        assert "error" in result

    async def test_whitespace_only_rejected(self, ctx):
        result = await done("  \n ", ctx)
        assert "error" in result


# ---------------------------------------------------------------------------
# send_message_to_user
# ---------------------------------------------------------------------------


class TestSendMessageToUser:
    async def test_sends_progress_message(self, ctx):
        result = await send_message_to_user("Building...", "progress", ctx)
        assert result["status"] == "ok"
        assert result["message_type"] == "progress"
        assert ctx.state["typed_messages"][0]["type"] == "progress"

    async def test_sends_warning_message(self, ctx):
        result = await send_message_to_user("Deprecated API", "warning", ctx)
        assert result["status"] == "ok"
        assert result["message_type"] == "warning"

    async def test_sends_error_message(self, ctx):
        result = await send_message_to_user("Build failed", "error", ctx)
        assert result["status"] == "ok"
        assert result["message_type"] == "error"

    async def test_default_type_is_progress(self, ctx):
        result = await send_message_to_user("Update", tool_context=ctx)
        assert result["message_type"] == "progress"

    async def test_invalid_type_rejected(self, ctx):
        result = await send_message_to_user("msg", "critical", ctx)
        assert "error" in result

    async def test_empty_message_rejected(self, ctx):
        result = await send_message_to_user("", "progress", ctx)
        assert "error" in result

    async def test_accumulates_typed_messages(self, ctx):
        await send_message_to_user("A", "progress", ctx)
        await send_message_to_user("B", "warning", ctx)
        assert len(ctx.state["typed_messages"]) == 2

    async def test_works_without_tool_context(self):
        result = await send_message_to_user("msg", "progress", tool_context=None)
        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# read_pr_comments
# ---------------------------------------------------------------------------


class TestReadPrComments:
    async def test_invalid_pr_number(self):
        result = await read_pr_comments(0)
        assert "error" in result

    async def test_negative_pr_number(self):
        result = await read_pr_comments(-1)
        assert "error" in result

    @patch("tools.communication_tools.asyncio.create_subprocess_exec")
    async def test_successful_read(self, mock_exec):
        import json
        comments_data = {
            "comments": [
                {
                    "author": {"login": "reviewer"},
                    "body": "LGTM",
                    "createdAt": "2026-01-01T00:00:00Z",
                }
            ]
        }
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(
            return_value=(json.dumps(comments_data).encode(), b"")
        )
        mock_exec.return_value = mock_proc

        result = await read_pr_comments(42)
        assert result["status"] == "ok"
        assert result["total_comments"] == 1
        assert result["comments"][0]["author"] == "reviewer"
        assert result["comments"][0]["body"] == "LGTM"

    @patch("tools.communication_tools.asyncio.create_subprocess_exec")
    async def test_gh_error(self, mock_exec):
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"not found"))
        mock_exec.return_value = mock_proc

        result = await read_pr_comments(999)
        assert "error" in result


# ---------------------------------------------------------------------------
# reply_to_pr_comments
# ---------------------------------------------------------------------------


class TestReplyToPrComments:
    async def test_invalid_pr_number(self):
        result = await reply_to_pr_comments(0, "reply")
        assert "error" in result

    async def test_empty_body_rejected(self):
        result = await reply_to_pr_comments(42, "")
        assert "error" in result

    @patch("tools.communication_tools.asyncio.create_subprocess_exec")
    async def test_successful_reply(self, mock_exec):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_exec.return_value = mock_proc

        result = await reply_to_pr_comments(42, "Thanks for the review!")
        assert result["status"] == "ok"
        assert result["pr_number"] == 42
        assert result["body"] == "Thanks for the review!"

    @patch("tools.communication_tools.asyncio.create_subprocess_exec")
    async def test_gh_error(self, mock_exec):
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"permission denied"))
        mock_exec.return_value = mock_proc

        result = await reply_to_pr_comments(42, "reply")
        assert "error" in result

