"""
Shell Tools — 3 tools for executing commands inside the workspace sandbox.

run_in_bash_session is the most-called tool during execution.
Frontend verification tools handle Playwright-based screenshot testing.

All tools are async for ADK parallelisation.
"""

import asyncio
import base64
import os

import subprocess
import aiofiles
from google.adk.tools import ToolContext
from utils.workspace_utils import get_workspace


async def run_in_bash_session(
    command: str, tool_context: ToolContext = None, workspace: str = ""
) -> dict:
    """Execute a bash command inside the workspace directory.

    Captures stdout and stderr. Timeout after 120 seconds.
    Most-used tool — called for installing deps, running tests, linting, etc.

    Emits AG-UI TOOL_CALL events + CUSTOM bashOutput artifact in production.
    """
    ws = workspace or get_workspace(tool_context)
    
    # Use subprocess.run via to_thread for Windows compatibility and simplicity
    def _run():
        return subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=ws,
            timeout=120
        )

    try:
        proc = await asyncio.to_thread(_run)
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "command": command,
        }
    except subprocess.TimeoutExpired:
        return {"error": "Command timed out after 120s", "command": command}
    except Exception as exc:
        return {"error": str(exc), "command": command}


async def frontend_verification_instructions(tool_context: ToolContext = None, _dummy: str = "") -> dict:
    """Return instructions for writing a Playwright test.

    The agent uses these instructions to write and run a visual test
    before submitting code that includes frontend changes.
    """
    instructions = """
Frontend Verification Steps:
1. Write a Playwright test file at /workspace/forge_scratchpad/test_frontend.py
2. The test should:
   a. Launch the dev server (if not already running)
   b. Navigate to the relevant page
   c. Wait for key elements to load
   d. Take a screenshot with page.screenshot()
   e. Assert key visual elements are present
3. Use the Chromium browser (pre-installed in container)
4. Save screenshots to /workspace/forge_scratchpad/screenshots/
5. After writing the test, call frontend_verification_complete()

Example test structure:
```python
from playwright.sync_api import sync_playwright

def test_frontend():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto("http://localhost:3000")
        page.wait_for_selector("h1")
        page.screenshot(path="/workspace/forge_scratchpad/screenshots/verify.png")
        browser.close()
```
""".strip()

    return {"instructions": instructions}


async def frontend_verification_complete(
    notes: str = "", tool_context: ToolContext = None, workspace: str = ""
) -> dict:
    """Run Playwright screenshot verification and return the result.

    Looks for screenshots in /workspace/screenshots/ and returns them
    as base64-encoded PNGs. Emits CUSTOM media artifact in production.
    """
    ws = workspace or WORKSPACE_ROOT
    screenshot_dir = os.path.join(ws, "forge_scratchpad", "screenshots")

    if not os.path.isdir(screenshot_dir):
        return {"error": "No screenshots directory found. Run tests first."}

    screenshots = []
    for fname in sorted(os.listdir(screenshot_dir)):
        if fname.lower().endswith((".png", ".jpg", ".jpeg")):
            fpath = os.path.join(screenshot_dir, fname)
            try:
                async with aiofiles.open(fpath, "rb") as f:
                    raw = await f.read()
                data = base64.b64encode(raw).decode("ascii")
                screenshots.append({"filename": fname, "base64": data})
            except Exception as exc:
                screenshots.append({"filename": fname, "error": str(exc)})

    if not screenshots:
        return {"error": "No screenshot files found in /workspace/forge_scratchpad/screenshots/"}

    return {
        "status": "ok",
        "notes": notes,
        "screenshots": screenshots,
        "count": len(screenshots),
    }
