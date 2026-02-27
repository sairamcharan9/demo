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
