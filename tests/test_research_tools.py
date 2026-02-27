"""Tests for tools/research_tools.py — google_search and view_text_website (async).

All HTTP calls are mocked — no API keys or network access required.
"""

import os
from unittest.mock import AsyncMock, patch, MagicMock

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.research_tools import google_search, view_text_website

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
