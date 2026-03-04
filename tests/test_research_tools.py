"""Tests for tools/research_tools.py — all 4 research tools (async).

All HTTP calls are mocked — no API keys or network access required.
"""

import os
from unittest.mock import AsyncMock, patch, MagicMock

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.research_tools import view_text_website, view_image, read_image_file

import pytest
import httpx


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
# view_image
# ---------------------------------------------------------------------------


class TestViewImage:
    async def test_empty_url(self):
        result = await view_image("")
        assert "error" in result

    async def test_invalid_scheme(self):
        result = await view_image("ftp://example.com/img.png")
        assert "error" in result
        assert "http" in result["error"]

    @patch("tools.research_tools.httpx.AsyncClient")
    async def test_successful_fetch(self, mock_client_cls):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.content = b"fake image content"
        mock_response.headers = {"content-type": "image/jpeg"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await view_image("https://example.com/img.jpg")
        assert result["status"] == "ok"
        assert result["url"] == "https://example.com/img.jpg"
        assert "base64" in result
        assert result["mime_type"] == "image/jpeg"

    @patch("tools.research_tools.httpx.AsyncClient")
    async def test_oversized_image(self, mock_client_cls):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.content = b"0" * (11 * 1024 * 1024)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await view_image("https://example.com/huge.png")
        assert "error" in result
        assert "too large" in result["error"]


# ---------------------------------------------------------------------------
# read_image_file
# ---------------------------------------------------------------------------


class TestReadImageFile:
    async def test_empty_path(self):
        result = await read_image_file("")
        assert "error" in result

    async def test_file_not_found(self, tmp_path):
        result = await read_image_file("missing.png", workspace=str(tmp_path))
        assert "error" in result
        assert "not found" in result["error"].lower()

    async def test_unsupported_format(self, tmp_path):
        (tmp_path / "file.txt").write_text("not an image")
        result = await read_image_file("file.txt", workspace=str(tmp_path))
        assert "error" in result
        assert "Unsupported" in result["error"]

    async def test_reads_png(self, tmp_path):
        fake_png = tmp_path / "test.png"
        fake_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

        result = await read_image_file("test.png", workspace=str(tmp_path))
        assert result["status"] == "ok"
        assert result["mime_type"] == "image/png"
        assert "base64" in result
        assert result["size_bytes"] == 58  # 8 header + 50 padding

    async def test_reads_jpeg(self, tmp_path):
        fake_jpg = tmp_path / "photo.jpg"
        fake_jpg.write_bytes(b"\xff\xd8\xff" + b"\x00" * 30)

        result = await read_image_file("photo.jpg", workspace=str(tmp_path))
        assert result["status"] == "ok"
        assert result["mime_type"] == "image/jpeg"

    async def test_path_traversal_blocked(self, tmp_path):
        result = await read_image_file("../../etc/passwd.png", workspace=str(tmp_path))
        assert "error" in result
        assert "escapes" in result["error"].lower() or "not found" in result["error"].lower()

    async def test_oversized_file(self, tmp_path):
        big_file = tmp_path / "huge.png"
        # Create a file > 10MB
        big_file.write_bytes(b"\x00" * (11 * 1024 * 1024))

        result = await read_image_file("huge.png", workspace=str(tmp_path))
        assert "error" in result
        assert "too large" in result["error"].lower()

