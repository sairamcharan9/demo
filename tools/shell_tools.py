"""
Shell Tools — 3 tools for executing commands inside the workspace sandbox.

run_in_bash_session is the most-called tool during execution.
Frontend verification tools handle Playwright-based screenshot testing.
"""

import subprocess
import base64
import os


WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT", "/workspace")


def run_in_bash_session(
    command: str, tool_context=None, workspace: str | None = None
) -> dict:
    """Execute a bash command inside the workspace directory.

    Captures stdout and stderr. Timeout after 120 seconds.
    Most-used tool — called for installing deps, running tests, linting, etc.

    Emits AG-UI TOOL_CALL events + CUSTOM bashOutput artifact in production.
    """
    ws = workspace or WORKSPACE_ROOT

    try:
        result = subprocess.run(
            ["bash", "-c", command],
            capture_output=True,
            text=True,
            cwd=ws,
            timeout=120,
            env={**os.environ, "HOME": "/root", "TERM": "dumb"},
        )
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": command,
        }
    except FileNotFoundError:
        # Windows fallback for local testing
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                cwd=ws,
                timeout=120,
                shell=True,
            )
            return {
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "command": command,
            }
        except Exception as exc:
            return {"error": str(exc), "command": command}
    except subprocess.TimeoutExpired:
        return {"error": "Command timed out after 120s", "command": command}
    except Exception as exc:
        return {"error": str(exc), "command": command}


def frontend_verification_instructions(tool_context=None) -> dict:
    """Return instructions for writing a Playwright test.

    The agent uses these instructions to write and run a visual test
    before submitting code that includes frontend changes.
    """
    instructions = """
Frontend Verification Steps:
1. Write a Playwright test file at /workspace/test_frontend.py
2. The test should:
   a. Launch the dev server (if not already running)
   b. Navigate to the relevant page
   c. Wait for key elements to load
   d. Take a screenshot with page.screenshot()
   e. Assert key visual elements are present
3. Use the Chromium browser (pre-installed in container)
4. Save screenshots to /workspace/screenshots/
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
        page.screenshot(path="/workspace/screenshots/verify.png")
        browser.close()
```
""".strip()

    return {"instructions": instructions}


def frontend_verification_complete(
    notes: str = "", tool_context=None, workspace: str | None = None
) -> dict:
    """Run Playwright screenshot verification and return the result.

    Looks for screenshots in /workspace/screenshots/ and returns them
    as base64-encoded PNGs. Emits CUSTOM media artifact in production.
    """
    ws = workspace or WORKSPACE_ROOT
    screenshot_dir = os.path.join(ws, "screenshots")

    if not os.path.isdir(screenshot_dir):
        return {"error": "No screenshots directory found. Run tests first."}

    screenshots = []
    for fname in sorted(os.listdir(screenshot_dir)):
        if fname.lower().endswith((".png", ".jpg", ".jpeg")):
            fpath = os.path.join(screenshot_dir, fname)
            try:
                with open(fpath, "rb") as f:
                    data = base64.b64encode(f.read()).decode("ascii")
                screenshots.append({"filename": fname, "base64": data})
            except Exception as exc:
                screenshots.append({"filename": fname, "error": str(exc)})

    if not screenshots:
        return {"error": "No screenshot files found in /workspace/screenshots/"}

    return {
        "status": "ok",
        "notes": notes,
        "screenshots": screenshots,
        "count": len(screenshots),
    }
