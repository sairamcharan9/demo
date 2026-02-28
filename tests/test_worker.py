"""Tests for worker/main.py — worker entry point."""

import os
from unittest.mock import AsyncMock, patch, MagicMock

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from worker.main import clone_repo, AUTOMATION_MODES

import pytest


class TestCloneRepo:
    async def test_skips_if_already_cloned(self, tmp_path):
        # Create a .git dir to simulate already-cloned repo
        (tmp_path / ".git").mkdir()
        # Should not raise or call git
        await clone_repo("https://github.com/test/repo.git", str(tmp_path))

    @patch("worker.main.asyncio.create_subprocess_exec")
    async def test_clones_repo(self, mock_exec, tmp_path):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_exec.return_value = mock_proc

        ws = str(tmp_path / "workspace")
        await clone_repo("https://github.com/test/repo.git", ws)

        # git clone should have been called
        first_call = mock_exec.call_args_list[0]
        args = first_call[0]
        assert "git" in args
        assert "clone" in args

    @patch("worker.main.asyncio.create_subprocess_exec")
    async def test_injects_github_token(self, mock_exec, tmp_path):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_exec.return_value = mock_proc

        ws = str(tmp_path / "workspace")
        await clone_repo(
            "https://github.com/test/repo.git",
            ws,
            github_token="ghp_test123",
        )

        first_call = mock_exec.call_args_list[0]
        args = first_call[0]
        # Token should be in the clone URL
        clone_url = [a for a in args if "github.com" in a][0]
        assert "ghp_test123" in clone_url

    @patch("worker.main.asyncio.create_subprocess_exec")
    async def test_clone_failure_raises(self, mock_exec, tmp_path):
        mock_proc = AsyncMock()
        mock_proc.returncode = 128
        mock_proc.communicate = AsyncMock(return_value=(b"", b"fatal: repo not found"))
        mock_exec.return_value = mock_proc

        ws = str(tmp_path / "workspace")
        with pytest.raises(RuntimeError, match="git clone failed"):
            await clone_repo("https://github.com/test/repo.git", ws)


class TestAutomationModes:
    def test_valid_modes(self):
        assert "NONE" in AUTOMATION_MODES
        assert "AUTO_APPROVE" in AUTOMATION_MODES
        assert "AUTO_CREATE_PR" in AUTOMATION_MODES

    def test_exactly_three_modes(self):
        assert len(AUTOMATION_MODES) == 3


class TestSessionStateInit:
    """Verify that create_session is called with all required state keys.

    ADK {key} injection only works if keys exist in session state. Every key
    referenced as {key} in the system prompt and every key tools read/write
    must be pre-seeded at session creation time.
    """

    REQUIRED_STATE_KEYS = {
        # System prompt {key} placeholders
        "automation_mode",
        "plan",
        "current_step",
        "completed_steps",
        "approved",
        "submitted",
        "task_complete",
        # Planning tools
        "awaiting_approval",
        # Communication tools
        "commit_message",
        "final_summary",
        "messages",
        "typed_messages",
        "awaiting_user_input",
        "user_input_prompt",
        # PR tracking
        "pr_url",
        "pr_number",
    }

    @patch("worker.main.Runner")
    @patch("worker.main.create_agent")
    @patch("worker.main.create_services")
    @patch("worker.main.clone_repo")
    async def test_session_created_with_all_required_keys(
        self, mock_clone, mock_services, mock_create_agent, mock_runner, monkeypatch
    ):
        monkeypatch.setenv("REPO_URL", "https://github.com/test/repo.git")
        monkeypatch.setenv("TASK", "Fix the bug")

        # Mock services
        mock_session_service = AsyncMock()
        mock_session = MagicMock()
        mock_session.id = "test-session"
        mock_session_service.create_session = AsyncMock(return_value=mock_session)
        mock_services.return_value = (mock_session_service, MagicMock())

        # Mock agent + runner
        mock_agent = MagicMock()
        mock_agent.name = "forge"
        mock_agent.model = "gemini-2.5-pro"
        mock_create_agent.return_value = mock_agent

        # run_async must be an async generator, not a sync iter
        async def empty_async_gen(*args, **kwargs):
            return
            yield  # noqa: makes this an async generator

        mock_runner_instance = MagicMock()
        mock_runner_instance.run_async = empty_async_gen
        mock_runner.return_value = mock_runner_instance

        from worker.main import run_worker
        await run_worker()

        # Verify create_session was called
        mock_session_service.create_session.assert_called_once()
        call_kwargs = mock_session_service.create_session.call_args
        state = call_kwargs.kwargs.get("state") or call_kwargs[1].get("state", {})

        # Every required key must be present
        missing = self.REQUIRED_STATE_KEYS - set(state.keys())
        assert not missing, f"Missing state keys: {missing}"

