"""
Research Tools — 2 tools for web research.

google_search uses the Google Custom Search JSON API.
view_text_website fetches a URL and extracts readable text.

Both require network access. API keys are read from environment variables.

All tools are async for ADK parallelisation.
"""

import os

import httpx
from bs4 import BeautifulSoup


# Max response size for view_text_website — 50KB of text
MAX_TEXT_BYTES = 50_000


async def google_search(
    query: str,
    num_results: int = 5,
    tool_context=None,
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
    tool_context=None,
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
