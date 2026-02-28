"""
End-to-end integration test — run the Forge agent against a real GitHub repo.

Clones https://github.com/sairamcharan9/calculator-app-assignment5 into a
temp workspace and asks the agent to add a square root function.

Requires GOOGLE_API_KEY env var (loaded from ../.env if present).

Usage:
    python -m pytest tests/test_e2e_agent.py -v -s
"""

import os
import sys
import subprocess
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import pytest
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part

from agent.agent import create_agent


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_URL = "https://github.com/sairamcharan9/calculator-app-assignment5"

TASK = "Add a square root function to the calculator app"

# Skip the entire module if no API key is set
pytestmark = pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"),
    reason="GOOGLE_API_KEY not set — skipping e2e tests",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path):
    """Clone the calculator repo into a temporary workspace."""
    ws = str(tmp_path / "workspace")

    result = subprocess.run(
        ["git", "clone", "--depth", "1", REPO_URL, ws],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"Clone failed: {result.stderr}"
    print(f"\n📁 Cloned repo into {ws}")

    return ws


# ---------------------------------------------------------------------------
# E2E Test
# ---------------------------------------------------------------------------


class TestE2EAgent:
    """Run the agent against the calculator repo and verify it completes."""

    async def test_adds_sqrt_to_calculator(self, workspace, monkeypatch):
        """Agent should orient, plan, write code, run tests, and commit."""
        monkeypatch.setenv("WORKSPACE_ROOT", workspace)

        # --- Setup agent + runner ---
        agent = create_agent()
        session_service = InMemorySessionService()
        runner = Runner(
            agent=agent,
            app_name="forge-e2e",
            session_service=session_service,
        )

        session = await session_service.create_session(
            app_name="forge-e2e",
            user_id="test-user",
            state={
                "automation_mode": "AUTO_APPROVE",
                "plan": [],
                "current_step": 0,
                "completed_steps": [],
                "approved": False,
                "awaiting_approval": False,
                "submitted": False,
                "commit_message": "",
                "task_complete": False,
                "final_summary": "",
                "messages": [],
                "typed_messages": [],
                "awaiting_user_input": False,
                "user_input_prompt": "",
                "pr_url": "",
                "pr_number": 0,
            },
        )

        # --- Run the agent (with retry for rate limits) ---
        user_message = Content(parts=[Part(text=(
            TASK
            + "\n\n[SYSTEM: Automation mode is AUTO_APPROVE. "
            "Auto-approve the plan without waiting for user review.]"
        ))])

        events = []
        tool_calls = []
        max_turns = 80  # generous limit for full e2e

        print("\n" + "=" * 60)
        print("FORGE E2E — Adding sqrt to calculator-app-assignment5")
        print("=" * 60)

        max_retries = 3
        retry_delay = 15

        for attempt in range(max_retries + 1):
            try:
                turn = 0
                async for event in runner.run_async(
                    session_id=session.id,
                    user_id="test-user",
                    new_message=user_message,
                ):
                    events.append(event)
                    turn += 1

                    if hasattr(event, "content") and event.content and event.content.parts:
                        for part in event.content.parts:
                            if hasattr(part, "text") and part.text:
                                print(f"\n[Turn {turn}] {part.text[:300]}")
                            if hasattr(part, "function_call") and part.function_call:
                                name = part.function_call.name
                                tool_calls.append(name)
                                print(f"  🔧 {name}({str(part.function_call.args)[:120]})")
                            if hasattr(part, "function_response") and part.function_response:
                                print(f"  📋 {str(part.function_response.response)[:200]}")

                    if turn >= max_turns:
                        print(f"\n⚠️ Safety limit reached ({max_turns} turns)")
                        break

                # If we get here, the loop finished successfully
                break

            except Exception as exc:
                exc_str = str(exc).lower()
                is_rate_limit = (
                    "429" in exc_str
                    or "resource exhausted" in exc_str
                    or "rate limit" in exc_str
                    or "quota" in exc_str
                    or "unavailable" in exc_str
                    or "overloaded" in exc_str
                    or "try again" in exc_str
                )
                if is_rate_limit and attempt < max_retries:
                    wait = retry_delay * (2 ** attempt)
                    print(f"\n⚠️ Rate limited (attempt {attempt + 1}/{max_retries}). Retrying in {wait}s...")
                    await asyncio.sleep(wait)
                    continue
                else:
                    raise

        print("\n" + "=" * 60)
        print(f"FORGE E2E — Done ({turn} turns, {len(tool_calls)} tool calls)")
        print(f"Tools used: {', '.join(sorted(set(tool_calls)))}")
        print("=" * 60)

        # ----- Assertions -----

        # Phase 0: Agent should have oriented
        orient_tools = {"list_files", "read_file"}
        assert orient_tools & set(tool_calls), (
            "Agent never called list_files or read_file (Phase 0 — Orient)"
        )

        # Phase 1: Agent should have created a plan
        assert "set_plan" in tool_calls, (
            "Agent never called set_plan (Phase 1 — Plan)"
        )

        # Phase 2: Agent should have written code
        write_tools = {"write_file", "replace_with_git_merge_diff"}
        assert write_tools & set(tool_calls), (
            "Agent never wrote any files (Phase 2 — Execute)"
        )

        # Verify sqrt was actually added to operations.py
        ops_path = os.path.join(workspace, "app", "operations.py")
        assert os.path.isfile(ops_path), "app/operations.py not found"
        ops_content = open(ops_path).read()
        assert "sqrt" in ops_content, (
            "sqrt not found in app/operations.py — agent failed to add it"
        )
        print(f"\n✅ app/operations.py contains 'sqrt'")

        # Verify tests were updated
        test_ops = os.path.join(workspace, "tests", "test_operations.py")
        if os.path.isfile(test_ops):
            test_content = open(test_ops).read()
            if "sqrt" in test_content:
                print("✅ tests/test_operations.py contains sqrt tests")
            else:
                print("⚠️ tests/test_operations.py exists but no sqrt tests")

        # Check if agent ran tests
        if "run_in_bash_session" in tool_calls:
            print("✅ Agent ran tests via run_in_bash_session")

        # Check if agent committed
        git_result = subprocess.run(
            ["git", "log", "--oneline", "-3"],
            capture_output=True, text=True, cwd=workspace,
        )
        print(f"\n📝 Git log:\n{git_result.stdout}")

        # If agent called done(), task_complete should be True
        if "done" in tool_calls:
            final_session = await session_service.get_session(
                app_name="forge-e2e",
                user_id="test-user",
                session_id=session.id,
            )
            assert final_session.state.get("task_complete") is True, (
                "Agent called done() but task_complete is not True"
            )
            print(f"✅ Task complete: {final_session.state.get('final_summary', '')[:200]}")
