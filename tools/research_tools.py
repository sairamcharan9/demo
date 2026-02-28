"""
Research Tools — 4 tools for web research and visual inspection.

google_search uses the Google Custom Search JSON API.
view_text_website fetches a URL and extracts readable text.
take_screenshot captures a URL via Playwright headless browser.
view_image reads an image file from the workspace and returns base64 content.

All tools are async for ADK parallelisation.
"""

import asyncio
import base64
import os

import aiofiles
import httpx
from bs4 import BeautifulSoup
from google.adk.tools import ToolContext


WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT", "/workspace")


# Max response size for view_text_website — 50KB of text
MAX_TEXT_BYTES = 50_000


async def google_search(
    query: str,
    num_results: int = 5,
    tool_context: ToolContext = None,
    workspace: str | None = None,
) -> dict:
    """Search the web via Google Custom Search JSON API.

    Returns a list of results with ``title``, ``link``, and ``snippet``.

    Requires env vars:
    - ``GOOGLE_SEARCH_API_KEY``
    - ``GOOGLE_SEARCH_CX`` (Custom Search Engine ID)
    """
    if not query or not query.strip():
        return {"error": "Query must not be empty"}

    api_key = os.environ.get("GOOGLE_SEARCH_API_KEY")
    cx = os.environ.get("GOOGLE_SEARCH_CX")

    if not api_key or not cx:
        return {
            "error": "Google Search not configured. "
            "Set GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX environment variables."
        }

    num_results = max(1, min(num_results, 10))  # API allows 1-10

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                "https://www.googleapis.com/customsearch/v1",
                params={
                    "key": api_key,
                    "cx": cx,
                    "q": query,
                    "num": num_results,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        return {"error": "Google Search request timed out"}
    except httpx.HTTPStatusError as exc:
        return {"error": f"Google Search HTTP error: {exc.response.status_code}"}
    except Exception as exc:
        return {"error": f"Google Search failed: {str(exc)}"}

    items = data.get("items", [])
    results = [
        {
            "title": item.get("title", ""),
            "link": item.get("link", ""),
            "snippet": item.get("snippet", ""),
        }
        for item in items
    ]

    return {
        "results": results,
        "total_results": data.get("searchInformation", {}).get("totalResults", "0"),
        "query": query,
    }


async def view_text_website(
    url: str,
    tool_context: ToolContext = None,
    workspace: str | None = None,
) -> dict:
    """Fetch a URL and extract readable text content.

    Uses BeautifulSoup to strip HTML and return plain text.
    Response is truncated to 50KB to prevent memory issues.
    """
    if not url or not url.strip():
        return {"error": "URL must not be empty"}

    if not url.startswith(("http://", "https://")):
        return {"error": "URL must start with http:// or https://"}

    try:
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ForgeBot/1.0)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.TimeoutException:
        return {"error": f"Request to {url} timed out"}
    except httpx.HTTPStatusError as exc:
        return {"error": f"HTTP error {exc.response.status_code} for {url}"}
    except Exception as exc:
        return {"error": f"Failed to fetch {url}: {str(exc)}"}

    content_type = resp.headers.get("content-type", "")
    if "text/html" in content_type:
        soup = BeautifulSoup(resp.text, "html.parser")
        # Remove script and style elements
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        text = soup.get_text(separator="\n", strip=True)
    else:
        # Plain text or other content — return as-is
        title = ""
        text = resp.text

    # Truncate to prevent oversized responses
    if len(text) > MAX_TEXT_BYTES:
        text = text[:MAX_TEXT_BYTES] + "\n\n[... truncated at 50KB ...]"

    return {
        "content": text,
        "title": title,
        "url": url,
        "content_length": len(text),
    }


def _resolve_safe_path(relative_path: str, workspace: str | None = None) -> str:
    """Resolve a path safely within the workspace boundary."""
    ws = workspace or WORKSPACE_ROOT
    resolved = os.path.normpath(os.path.join(ws, relative_path))
    if not resolved.startswith(os.path.normpath(ws)):
        raise ValueError(f"Path escapes workspace: {relative_path}")
    return resolved


async def take_screenshot(
    url: str,
    output_filename: str = "screenshot.png",
    tool_context: ToolContext = None,
    workspace: str | None = None,
) -> dict:
    """Capture a screenshot of a URL using Playwright headless Chromium.

    Saves the screenshot to /workspace/screenshots/<output_filename> and
    returns the base64-encoded PNG. Requires Playwright + Chromium to be
    installed in the container.
    """
    if not url or not url.strip():
        return {"error": "URL must not be empty"}

    if not url.startswith(("http://", "https://")):
        return {"error": "URL must start with http:// or https://"}

    ws = workspace or WORKSPACE_ROOT
    screenshot_dir = os.path.join(ws, "screenshots")
    os.makedirs(screenshot_dir, exist_ok=True)
    output_path = os.path.join(screenshot_dir, output_filename)

    try:
        proc = await asyncio.create_subprocess_exec(
            "python3", "-c",
            f"""
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={{'width': 1280, 'height': 720}})
    page.goto("{url}", wait_until="networkidle", timeout=30000)
    page.screenshot(path="{output_path}", full_page=True)
    browser.close()
""",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)

        if proc.returncode != 0:
            return {"error": f"Screenshot failed: {stderr.decode().strip()}"}

    except asyncio.TimeoutError:
        return {"error": "Screenshot timed out after 60s"}
    except FileNotFoundError:
        return {"error": "python3 not found — cannot run Playwright"}

    # Read and encode the screenshot
    if not os.path.isfile(output_path):
        return {"error": f"Screenshot file not created at {output_path}"}

    try:
        async with aiofiles.open(output_path, "rb") as f:
            raw = await f.read()
        encoded = base64.b64encode(raw).decode("ascii")
    except Exception as exc:
        return {"error": f"Failed to read screenshot: {str(exc)}"}

    return {
        "status": "ok",
        "path": output_path,
        "base64": encoded,
        "size_bytes": len(raw),
        "url": url,
    }


async def view_image(
    path: str,
    tool_context: ToolContext = None,
    workspace: str | None = None,
) -> dict:
    """Read an image file from the workspace and return base64-encoded content.

    Useful for inspecting screenshots, diagrams, or other images the agent
    needs to reason about. Max file size: 10MB.
    """
    if not path or not path.strip():
        return {"error": "Path must not be empty"}

    try:
        resolved = _resolve_safe_path(path, workspace)
    except ValueError as exc:
        return {"error": str(exc)}

    if not os.path.isfile(resolved):
        return {"error": f"File not found: {path}"}

    # Validate extension
    valid_ext = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg")
    if not path.lower().endswith(valid_ext):
        return {"error": f"Unsupported image format. Supported: {', '.join(valid_ext)}"}

    # Check file size (max 10MB)
    size = os.path.getsize(resolved)
    if size > 10 * 1024 * 1024:
        return {"error": f"Image too large ({size} bytes). Max 10MB."}

    try:
        async with aiofiles.open(resolved, "rb") as f:
            raw = await f.read()
        encoded = base64.b64encode(raw).decode("ascii")
    except Exception as exc:
        return {"error": f"Failed to read image: {str(exc)}"}

    ext = os.path.splitext(path)[1].lstrip(".").lower()
    mime_map = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
        "bmp": "image/bmp",
        "svg": "image/svg+xml",
    }

    return {
        "status": "ok",
        "path": path,
        "base64": encoded,
        "size_bytes": size,
        "mime_type": mime_map.get(ext, "application/octet-stream"),
    }
