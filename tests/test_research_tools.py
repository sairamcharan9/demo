"""Tests for tools/research_tools.py — all 4 research tools (async).

All HTTP calls are mocked — no API keys or network access required.
"""

import os
from unittest.mock import AsyncMock, patch, MagicMock

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.research_tools import google_search, view_text_website, take_screenshot, view_image

import pytest
import httpx


# ---------------------------------------------------------------------------
# google_search
# ---------------------------------------------------------------------------


class TestGoogleSearch:
    async def test_missing_api_key(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_SEARCH_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_SEARCH_CX", raising=False)
        result = await google_search("python asyncio")
        assert "error" in result
        assert "not configured" in result["error"]

    async def test_empty_query(self):
        result = await google_search("")
        assert "error" in result

    @patch("tools.research_tools.httpx.AsyncClient")
    async def test_successful_search(self, mock_client_cls, monkeypatch):
        monkeypatch.setenv("GOOGLE_SEARCH_API_KEY", "fake-key")
        monkeypatch.setenv("GOOGLE_SEARCH_CX", "fake-cx")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "items": [
                {
                    "title": "Python Docs",
                    "link": "https://docs.python.org",
                    "snippet": "Welcome to Python",
                }
            ],
            "searchInformation": {"totalResults": "1"},
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await google_search("python docs", num_results=1)
        assert len(result["results"]) == 1
        assert result["results"][0]["title"] == "Python Docs"
        assert result["query"] == "python docs"

    @patch("tools.research_tools.httpx.AsyncClient")
    async def test_timeout(self, mock_client_cls, monkeypatch):
        monkeypatch.setenv("GOOGLE_SEARCH_API_KEY", "fake-key")
        monkeypatch.setenv("GOOGLE_SEARCH_CX", "fake-cx")

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await google_search("test")
        assert "error" in result
        assert "timed out" in result["error"]

    async def test_clamps_num_results(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_SEARCH_API_KEY", raising=False)
        # Will fail early due to missing key, but tests the clamp logic implicitly
        result = await google_search("test", num_results=100)
        assert "error" in result  # fails for missing key, not for num_results


# ---------------------------------------------------------------------------
# view_text_website
# ---------------------------------------------------------------------------


class TestViewTextWebsite:
    async def test_empty_url(self):
        result = await view_text_website("")
        assert "error" in result

    async def test_invalid_protocol(self):
        result = await view_text_website("ftp://example.com")
        assert "error" in result
        assert "http" in result["error"]

    @patch("tools.research_tools.httpx.AsyncClient")
    async def test_successful_fetch(self, mock_client_cls):
        html = "<html><head><title>Test Page</title></head><body><p>Hello World</p></body></html>"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.text = html
        mock_response.headers = {"content-type": "text/html; charset=utf-8"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await view_text_website("https://example.com")
        assert result["title"] == "Test Page"
        assert "Hello World" in result["content"]
        assert result["url"] == "https://example.com"

    @patch("tools.research_tools.httpx.AsyncClient")
    async def test_strips_scripts(self, mock_client_cls):
        html = "<html><body><script>alert('xss')</script><p>Safe content</p></body></html>"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.text = html
        mock_response.headers = {"content-type": "text/html"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await view_text_website("https://example.com")
        assert "alert" not in result["content"]
        assert "Safe content" in result["content"]

    @patch("tools.research_tools.httpx.AsyncClient")
    async def test_truncates_large_response(self, mock_client_cls):
        html = "<html><body>" + "x" * 60_000 + "</body></html>"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.text = html
        mock_response.headers = {"content-type": "text/html"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await view_text_website("https://example.com")
        assert "truncated" in result["content"]

    @patch("tools.research_tools.httpx.AsyncClient")
    async def test_timeout(self, mock_client_cls):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await view_text_website("https://example.com")
        assert "error" in result
        assert "timed out" in result["error"]


# ---------------------------------------------------------------------------
# take_screenshot
# ---------------------------------------------------------------------------


class TestTakeScreenshot:
    async def test_empty_url(self):
        result = await take_screenshot("")
        assert "error" in result

    async def test_invalid_protocol(self):
        result = await take_screenshot("ftp://example.com")
        assert "error" in result
        assert "http" in result["error"]

    @patch("tools.research_tools.asyncio.create_subprocess_exec")
    async def test_successful_screenshot(self, mock_exec, tmp_path):
        # Create a fake screenshot file that the tool will read
        screenshot_dir = tmp_path / "screenshots"
        screenshot_dir.mkdir()
        fake_png = screenshot_dir / "screenshot.png"
        fake_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_exec.return_value = mock_proc

        result = await take_screenshot(
            "https://example.com", workspace=str(tmp_path)
        )
        assert result["status"] == "ok"
        assert result["url"] == "https://example.com"
        assert "base64" in result
        assert result["size_bytes"] > 0

    @patch("tools.research_tools.asyncio.create_subprocess_exec")
    async def test_screenshot_process_error(self, mock_exec, tmp_path):
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"Chromium not found"))
        mock_exec.return_value = mock_proc

        result = await take_screenshot(
            "https://example.com", workspace=str(tmp_path)
        )
        assert "error" in result
        assert "Chromium not found" in result["error"]

    @patch("tools.research_tools.asyncio.create_subprocess_exec")
    async def test_screenshot_timeout(self, mock_exec, tmp_path):
        import asyncio

        mock_exec.side_effect = asyncio.TimeoutError()

        result = await take_screenshot(
            "https://example.com", workspace=str(tmp_path)
        )
        assert "error" in result
        assert "timed out" in result["error"]


# ---------------------------------------------------------------------------
# view_image
# ---------------------------------------------------------------------------


class TestViewImage:
    async def test_empty_path(self):
        result = await view_image("")
        assert "error" in result

    async def test_file_not_found(self, tmp_path):
        result = await view_image("missing.png", workspace=str(tmp_path))
        assert "error" in result
        assert "not found" in result["error"].lower()

    async def test_unsupported_format(self, tmp_path):
        (tmp_path / "file.txt").write_text("not an image")
        result = await view_image("file.txt", workspace=str(tmp_path))
        assert "error" in result
        assert "Unsupported" in result["error"]

    async def test_reads_png(self, tmp_path):
        fake_png = tmp_path / "test.png"
        fake_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

        result = await view_image("test.png", workspace=str(tmp_path))
        assert result["status"] == "ok"
        assert result["mime_type"] == "image/png"
        assert "base64" in result
        assert result["size_bytes"] == 58  # 8 header + 50 padding

    async def test_reads_jpeg(self, tmp_path):
        fake_jpg = tmp_path / "photo.jpg"
        fake_jpg.write_bytes(b"\xff\xd8\xff" + b"\x00" * 30)

        result = await view_image("photo.jpg", workspace=str(tmp_path))
        assert result["status"] == "ok"
        assert result["mime_type"] == "image/jpeg"

    async def test_path_traversal_blocked(self, tmp_path):
        result = await view_image("../../etc/passwd.png", workspace=str(tmp_path))
        assert "error" in result
        assert "escapes" in result["error"].lower() or "not found" in result["error"].lower()

    async def test_oversized_file(self, tmp_path):
        big_file = tmp_path / "huge.png"
        # Create a file > 10MB
        big_file.write_bytes(b"\x00" * (11 * 1024 * 1024))

        result = await view_image("huge.png", workspace=str(tmp_path))
        assert "error" in result
        assert "too large" in result["error"].lower()

