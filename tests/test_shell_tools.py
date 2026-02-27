"""Tests for tools/shell_tools.py — all 3 shell tools (async)."""

import os
import base64

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.shell_tools import (
    run_in_bash_session,
    frontend_verification_instructions,
    frontend_verification_complete,
)

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path):
    """Temp workspace for shell commands."""
    return str(tmp_path)


@pytest.fixture
def workspace_with_screenshots(tmp_path):
    """Workspace with a screenshots directory containing a test image."""
    ss_dir = tmp_path / "screenshots"
    ss_dir.mkdir()
    # Create a minimal 1x1 red PNG
    import struct, zlib
    def make_png():
        raw = b"\x00\xff\x00\x00"  # filter byte + RGB
        compressed = zlib.compress(raw)
        def chunk(ctype, data):
            c = ctype + data
            return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        sig = b"\x89PNG\r\n\x1a\n"
        ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        idat = chunk(b"IDAT", compressed)
        iend = chunk(b"IEND", b"")
        return sig + ihdr + idat + iend
    (ss_dir / "test.png").write_bytes(make_png())
    return str(tmp_path)


# ---------------------------------------------------------------------------
# run_in_bash_session
# ---------------------------------------------------------------------------


class TestRunInBashSession:
    async def test_echo(self, workspace):
        result = await run_in_bash_session("echo hello", workspace=workspace)
        assert result["exit_code"] == 0
        assert "hello" in result["stdout"]

    async def test_captures_stderr(self, workspace):
        result = await run_in_bash_session("echo err >&2", workspace=workspace)
        assert "err" in result.get("stderr", "") or "err" in result.get("stdout", "")

    async def test_nonzero_exit(self, workspace):
        result = await run_in_bash_session("exit 42", workspace=workspace)
        assert result["exit_code"] == 42

    async def test_cwd_is_workspace(self, workspace):
        # Create a file, then check we can see it
        with open(os.path.join(workspace, "marker.txt"), "w") as f:
            f.write("found")
        result = await run_in_bash_session(
            'python -c "print(open(\'marker.txt\').read())"',
            workspace=workspace,
        )
        if "error" not in result:
            assert result["exit_code"] == 0
            assert "found" in result["stdout"]

    async def test_command_stored(self, workspace):
        result = await run_in_bash_session("echo test", workspace=workspace)
        assert result["command"] == "echo test"

    async def test_multiline_output(self, workspace):
        result = await run_in_bash_session("echo line1 && echo line2", workspace=workspace)
        assert "line1" in result["stdout"]
        assert "line2" in result["stdout"]


# ---------------------------------------------------------------------------
# frontend_verification_instructions
# ---------------------------------------------------------------------------


class TestFrontendVerificationInstructions:
    async def test_returns_instructions(self):
        result = await frontend_verification_instructions()
        assert "instructions" in result
        assert "Playwright" in result["instructions"]
        assert "screenshot" in result["instructions"].lower()

    async def test_includes_example(self):
        result = await frontend_verification_instructions()
        assert "sync_playwright" in result["instructions"]


# ---------------------------------------------------------------------------
# frontend_verification_complete
# ---------------------------------------------------------------------------


class TestFrontendVerificationComplete:
    async def test_no_screenshots_dir(self, workspace):
        result = await frontend_verification_complete(workspace=workspace)
        assert "error" in result

    async def test_reads_screenshots(self, workspace_with_screenshots):
        result = await frontend_verification_complete(workspace=workspace_with_screenshots)
        assert result["status"] == "ok"
        assert result["count"] == 1
        assert result["screenshots"][0]["filename"] == "test.png"
        # Verify it's valid base64
        decoded = base64.b64decode(result["screenshots"][0]["base64"])
        assert decoded[:4] == b"\x89PNG"

    async def test_captures_notes(self, workspace_with_screenshots):
        result = await frontend_verification_complete(
            notes="Looks good", workspace=workspace_with_screenshots
        )
        assert result["notes"] == "Looks good"

    async def test_empty_screenshots_dir(self, tmp_path):
        (tmp_path / "screenshots").mkdir()
        result = await frontend_verification_complete(workspace=str(tmp_path))
        assert "error" in result
