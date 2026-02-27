"""Tests for tools/file_tools.py — all 8 file tools (async)."""

import os
import subprocess

# Allow imports from project root
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

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

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path):
    """Create a temporary workspace with sample files."""
    # Create a simple file structure
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "src" / "utils.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# My Project\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("def test_pass():\n    assert True\n", encoding="utf-8")
    return str(tmp_path)


@pytest.fixture
def git_workspace(tmp_path):
    """Create a workspace that is a git repo for restore/reset tests."""
    (tmp_path / "file.txt").write_text("original content\n", encoding="utf-8")

    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)

    return str(tmp_path)


# ---------------------------------------------------------------------------
# list_files
# ---------------------------------------------------------------------------


class TestListFiles:
    async def test_lists_files(self, workspace):
        result = await list_files(".", workspace=workspace)
        assert "files" in result
        assert "tree" in result
        assert len(result["files"]) == 4

    async def test_lists_subdirectory(self, workspace):
        result = await list_files("src", workspace=workspace)
        assert "main.py" in result["files"]
        assert "utils.py" in result["files"]

    async def test_nonexistent_directory(self, workspace):
        result = await list_files("nonexistent", workspace=workspace)
        assert "error" in result

    async def test_skips_hidden_dirs(self, workspace):
        os.makedirs(os.path.join(workspace, ".git"))
        with open(os.path.join(workspace, ".git", "config"), "w") as f:
            f.write("test")
        result = await list_files(".", workspace=workspace)
        # .git/config should NOT appear
        assert not any(".git" in f for f in result["files"])


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------


class TestReadFile:
    async def test_reads_content(self, workspace):
        result = await read_file("README.md", workspace=workspace)
        assert result["content"] == "# My Project\n"
        assert result["lines"] == 1

    async def test_numbered_lines(self, workspace):
        result = await read_file("src/utils.py", workspace=workspace)
        assert "   1 |" in result["numbered"]
        assert result["lines"] == 2

    async def test_nonexistent_file(self, workspace):
        result = await read_file("ghost.txt", workspace=workspace)
        assert "error" in result


# ---------------------------------------------------------------------------
# write_file
# ---------------------------------------------------------------------------


class TestWriteFile:
    async def test_creates_file(self, workspace):
        result = await write_file("new.txt", "hello world", workspace=workspace)
        assert result["status"] == "ok"
        assert os.path.isfile(os.path.join(workspace, "new.txt"))

    async def test_creates_nested_directories(self, workspace):
        result = await write_file("deep/nested/file.py", "x = 1", workspace=workspace)
        assert result["status"] == "ok"
        assert os.path.isfile(os.path.join(workspace, "deep", "nested", "file.py"))

    async def test_overwrites_existing(self, workspace):
        await write_file("README.md", "new content", workspace=workspace)
        result = await read_file("README.md", workspace=workspace)
        assert result["content"] == "new content"

    async def test_returns_byte_count(self, workspace):
        result = await write_file("size.txt", "12345", workspace=workspace)
        assert result["bytes"] == 5


# ---------------------------------------------------------------------------
# delete_file
# ---------------------------------------------------------------------------


class TestDeleteFile:
    async def test_deletes_file(self, workspace):
        result = await delete_file("README.md", workspace=workspace)
        assert result["status"] == "ok"
        assert not os.path.exists(os.path.join(workspace, "README.md"))

    async def test_deletes_directory(self, workspace):
        result = await delete_file("src", workspace=workspace)
        assert result["status"] == "ok"
        assert not os.path.exists(os.path.join(workspace, "src"))

    async def test_nonexistent(self, workspace):
        result = await delete_file("ghost.txt", workspace=workspace)
        assert "error" in result


# ---------------------------------------------------------------------------
# rename_file
# ---------------------------------------------------------------------------


class TestRenameFile:
    async def test_renames_file(self, workspace):
        result = await rename_file("README.md", "DOCS.md", workspace=workspace)
        assert result["status"] == "ok"
        assert not os.path.exists(os.path.join(workspace, "README.md"))
        assert os.path.isfile(os.path.join(workspace, "DOCS.md"))

    async def test_moves_to_subdirectory(self, workspace):
        result = await rename_file("README.md", "docs/README.md", workspace=workspace)
        assert result["status"] == "ok"
        assert os.path.isfile(os.path.join(workspace, "docs", "README.md"))

    async def test_source_not_found(self, workspace):
        result = await rename_file("ghost.txt", "renamed.txt", workspace=workspace)
        assert "error" in result


# ---------------------------------------------------------------------------
# Path traversal protection
# ---------------------------------------------------------------------------


class TestPathTraversal:
    async def test_read_blocked(self, workspace):
        with pytest.raises(ValueError):
            await read_file("../../etc/passwd", workspace=workspace)

    async def test_write_blocked(self, workspace):
        with pytest.raises(ValueError):
            await write_file("../../evil.sh", "rm -rf /", workspace=workspace)

    async def test_delete_blocked(self, workspace):
        with pytest.raises(ValueError):
            await delete_file("../../../etc/hosts", workspace=workspace)


# ---------------------------------------------------------------------------
# restore_file (requires git)
# ---------------------------------------------------------------------------


class TestRestoreFile:
    async def test_restores_modified_file(self, git_workspace):
        # Modify the committed file
        with open(os.path.join(git_workspace, "file.txt"), "w") as f:
            f.write("modified content\n")

        result = await restore_file("file.txt", workspace=git_workspace)
        assert result["status"] == "ok"

        with open(os.path.join(git_workspace, "file.txt")) as f:
            assert f.read() == "original content\n"


# ---------------------------------------------------------------------------
# reset_all (requires git)
# ---------------------------------------------------------------------------


class TestResetAll:
    async def test_resets_workspace(self, git_workspace):
        # Modify the committed file
        with open(os.path.join(git_workspace, "file.txt"), "w") as f:
            f.write("modified\n")

        # Add a new untracked file should remain after reset --hard
        # but staged files should be reset
        subprocess.run(["git", "add", "."], cwd=git_workspace, capture_output=True)

        result = await reset_all(workspace=git_workspace)
        assert result["status"] == "ok"

        with open(os.path.join(git_workspace, "file.txt")) as f:
            assert f.read() == "original content\n"


# ---------------------------------------------------------------------------
# replace_with_git_merge_diff (requires git)
# ---------------------------------------------------------------------------


class TestReplaceWithGitMergeDiff:
    async def test_applies_diff(self, git_workspace):
        diff = """diff --git a/file.txt b/file.txt
index 1234567..abcdefg 100644
--- a/file.txt
+++ b/file.txt
@@ -1 +1,2 @@
 original content
+added line
"""
        result = await replace_with_git_merge_diff("file.txt", diff, workspace=git_workspace)
        assert result["status"] == "ok"

        with open(os.path.join(git_workspace, "file.txt")) as f:
            content = f.read()
            assert "added line" in content
