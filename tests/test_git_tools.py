"""Tests for tools/git_tools.py — all 4 git tools (async).

make_commit and create_branch tests use a real git repo (git_workspace fixture).
watch_pr_ci_status and create_pr tests mock the gh CLI since they need a real PR.
"""

import os
import subprocess
from unittest.mock import AsyncMock, patch

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.git_tools import make_commit, watch_pr_ci_status, create_branch, create_pr

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def git_workspace(tmp_path):
    """Create a workspace that is a git repo with an initial commit."""
    (tmp_path / "file.txt").write_text("original content\n", encoding="utf-8")

    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)

    return str(tmp_path)


# ---------------------------------------------------------------------------
# make_commit
# ---------------------------------------------------------------------------


class TestMakeCommit:
    async def test_commits_changes(self, git_workspace):
        # Make a change
        with open(os.path.join(git_workspace, "file.txt"), "w") as f:
            f.write("modified\n")

        result = await make_commit("feat: modify file", workspace=git_workspace)
        assert result["status"] == "ok"
        assert len(result["sha"]) == 40  # full SHA
        assert result["message"] == "feat: modify file"

        # Verify the commit exists
        log = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=git_workspace,
            capture_output=True,
            text=True,
        )
        assert "feat: modify file" in log.stdout

    async def test_commits_new_file(self, git_workspace):
        with open(os.path.join(git_workspace, "new.py"), "w") as f:
            f.write("print('new')\n")

        result = await make_commit("feat: add new file", workspace=git_workspace)
        assert result["status"] == "ok"

    async def test_nothing_to_commit(self, git_workspace):
        result = await make_commit("empty commit", workspace=git_workspace)
        assert "error" in result
        assert "nothing to commit" in result["error"].lower()

    async def test_empty_message_rejected(self, git_workspace):
        result = await make_commit("", workspace=git_workspace)
        assert "error" in result


# ---------------------------------------------------------------------------
# watch_pr_ci_status
# ---------------------------------------------------------------------------


class TestWatchPrCiStatus:
    async def test_invalid_pr_number(self):
        result = await watch_pr_ci_status(0)
        assert "error" in result

    async def test_negative_pr_number(self):
        result = await watch_pr_ci_status(-5)
        assert "error" in result

    @patch("tools.git_tools.asyncio.create_subprocess_exec")
    async def test_all_checks_pass(self, mock_exec):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(
            b"build\tpass\t2m30s\thttps://ci.example.com/1\nlint\tpass\t30s\thttps://ci.example.com/2\n",
            b"",
        ))
        mock_exec.return_value = mock_proc

        result = await watch_pr_ci_status(42)
        assert result["status"] == "pass"
        assert result["total_checks"] == 2
        assert result["checks"][0]["name"] == "build"
        assert result["checks"][0]["status"] == "pass"

    @patch("tools.git_tools.asyncio.create_subprocess_exec")
    async def test_some_checks_failing(self, mock_exec):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(
            b"build\tfail\t1m\thttps://ci.example.com/1\nlint\tpass\t30s\thttps://ci.example.com/2\n",
            b"",
        ))
        mock_exec.return_value = mock_proc

        result = await watch_pr_ci_status(42)
        assert result["status"] == "failing"

    @patch("tools.git_tools.asyncio.create_subprocess_exec")
    async def test_no_checks(self, mock_exec):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_exec.return_value = mock_proc

        result = await watch_pr_ci_status(42)
        assert result["status"] == "pending"


# ---------------------------------------------------------------------------
# create_branch
# ---------------------------------------------------------------------------


class TestCreateBranch:
    async def test_creates_branch(self, git_workspace):
        result = await create_branch("feat/new-feature", workspace=git_workspace)
        assert result["status"] == "ok"
        assert result["branch"] == "feat/new-feature"

        # Verify we're on the new branch
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=git_workspace,
            capture_output=True,
            text=True,
        )
        assert branch.stdout.strip() == "feat/new-feature"

    async def test_empty_name_rejected(self):
        result = await create_branch("")
        assert "error" in result

    async def test_invalid_name_rejected(self):
        result = await create_branch("bad branch name!")
        assert "error" in result
        assert "Invalid" in result["error"]

    async def test_double_dot_rejected(self):
        result = await create_branch("feat..fix")
        assert "error" in result

    async def test_trailing_slash_rejected(self):
        result = await create_branch("feat/")
        assert "error" in result

    async def test_lock_extension_rejected(self):
        result = await create_branch("refs.lock")
        assert "error" in result

    async def test_branch_already_exists(self, git_workspace):
        # Create branch first
        await create_branch("existing-branch", workspace=git_workspace)
        # Switch back to main
        subprocess.run(["git", "checkout", "-"], cwd=git_workspace, capture_output=True)
        # Try creating again
        result = await create_branch("existing-branch", workspace=git_workspace)
        assert "error" in result
        assert "already exists" in result["error"]


# ---------------------------------------------------------------------------
# create_pr
# ---------------------------------------------------------------------------


class TestCreatePr:
    async def test_empty_title_rejected(self):
        result = await create_pr("")
        assert "error" in result

    @patch("tools.git_tools.asyncio.create_subprocess_exec")
    async def test_successful_pr_creation(self, mock_exec):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(
            b"https://github.com/org/repo/pull/42\n",
            b"",
        ))
        mock_exec.return_value = mock_proc

        result = await create_pr("feat: add login", body="Adds login page")
        assert result["status"] == "ok"
        assert result["pr_url"] == "https://github.com/org/repo/pull/42"
        assert result["pr_number"] == 42
        assert result["title"] == "feat: add login"

    @patch("tools.git_tools.asyncio.create_subprocess_exec")
    async def test_pr_with_branch(self, mock_exec):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(
            b"https://github.com/org/repo/pull/10\n",
            b"",
        ))
        mock_exec.return_value = mock_proc

        result = await create_pr("fix: typo", branch="fix/typo")
        assert result["status"] == "ok"
        # Verify --head was passed
        call_args = mock_exec.call_args[0]
        assert "--head" in call_args
        assert "fix/typo" in call_args

    @patch("tools.git_tools.asyncio.create_subprocess_exec")
    async def test_gh_error(self, mock_exec):
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"no upstream configured"))
        mock_exec.return_value = mock_proc

        result = await create_pr("test PR")
        assert "error" in result
        assert "no upstream" in result["error"]

