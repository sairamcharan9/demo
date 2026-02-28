"""Tests for agent/agent.py — agent creation, tool registration, and callbacks."""

import os

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.agent import (
    create_agent,
    ALL_TOOLS,
    SYSTEM_PROMPT,
    before_model_callback,
    after_tool_callback,
    _infer_phase,
)

import pytest


class TestCreateAgent:
    def test_creates_agent(self):
        agent = create_agent()
        assert agent.name == "forge"

    def test_default_model(self, monkeypatch):
        monkeypatch.delenv("GEMINI_MODEL", raising=False)
        agent = create_agent()
        assert agent.model == "gemini-2.5-pro"

    def test_custom_model_via_arg(self):
        agent = create_agent(model="gemini-2.0-flash")
        assert agent.model == "gemini-2.0-flash"

    def test_custom_model_via_env(self, monkeypatch):
        monkeypatch.setenv("GEMINI_MODEL", "gemini-2.0-flash")
        agent = create_agent()
        assert agent.model == "gemini-2.0-flash"

    def test_custom_name(self):
        agent = create_agent(name="custom_agent")
        assert agent.name == "custom_agent"

    def test_has_tools(self):
        agent = create_agent()
        assert len(agent.tools) == 32

    def test_has_instruction(self):
        agent = create_agent()
        assert agent.instruction is not None
        assert len(agent.instruction) > 100

    def test_has_description(self):
        agent = create_agent()
        assert agent.description is not None

    def test_has_callbacks(self):
        agent = create_agent()
        assert agent.before_model_callback is not None
        assert agent.after_tool_callback is not None


class TestAllTools:
    def test_tool_count(self):
        assert len(ALL_TOOLS) == 32

    def test_all_tools_are_callable(self):
        for tool in ALL_TOOLS:
            assert callable(tool), f"{tool} is not callable"

    def test_all_tools_are_async(self):
        import asyncio
        for tool in ALL_TOOLS:
            assert asyncio.iscoroutinefunction(tool), f"{tool.__name__} is not async"


class TestSystemPrompt:
    def test_mentions_all_phases(self):
        for phase in ["Phase 0", "Phase 1", "Phase 2", "Phase 3", "Phase 4"]:
            assert phase in SYSTEM_PROMPT

    def test_mentions_key_tools(self):
        key_tools = [
            "list_files", "read_file", "set_plan", "request_plan_review",
            "write_file", "run_in_bash_session", "make_commit", "submit", "done",
        ]
        for tool_name in key_tools:
            assert tool_name in SYSTEM_PROMPT, f"{tool_name} not in system prompt"


class TestCallbacks:
    """Verify _infer_phase logic and callback functions."""

    def test_phase_orient_no_plan(self):
        assert _infer_phase({}) == "Phase 0 — Orient"

    def test_phase_plan_unapproved(self):
        assert _infer_phase({"plan": ["a"], "approved": False}) == "Phase 1 — Plan"

    def test_phase_execute_in_progress(self):
        state = {"plan": ["a", "b"], "approved": True, "completed_steps": [{"step_index": 0}]}
        assert _infer_phase(state) == "Phase 2 — Execute"

    def test_phase_verify_all_complete(self):
        state = {"plan": ["a"], "approved": True, "completed_steps": [{"step_index": 0}]}
        assert _infer_phase(state) == "Phase 3 — Verify"

    def test_phase_submit(self):
        assert _infer_phase({"submitted": True}) == "Phase 4 — Submit"

    def test_phase_done(self):
        assert _infer_phase({"task_complete": True}) == "DONE"

    async def test_before_model_returns_none(self):
        """before_model_callback should return None (let model proceed)."""
        from unittest.mock import MagicMock
        ctx = MagicMock()
        ctx.state = {"plan": [], "current_step": 0, "completed_steps": [], "approved": False, "submitted": False}
        result = await before_model_callback(ctx, llm_request=MagicMock())
        assert result is None

    async def test_after_tool_returns_none(self):
        """after_tool_callback should return None (pass through response)."""
        from unittest.mock import MagicMock
        tool = MagicMock()
        tool.name = "test_tool"
        ctx = MagicMock()
        result = await after_tool_callback(tool=tool, args={}, tool_context=ctx, tool_response={"status": "ok"})
        assert result is None


class TestStateInjectionKeys:
    """Verify system prompt {key} placeholders match actual state keys."""

    def test_all_placeholders_are_valid_state_keys(self):
        import re
        # Extract all {key} placeholders from the system prompt
        placeholders = set(re.findall(r"\{(\w+)\}", SYSTEM_PROMPT))

        # These are the keys pre-seeded in worker/main.py create_session()
        valid_state_keys = {
            "automation_mode", "plan", "current_step", "completed_steps",
            "approved", "submitted", "task_complete", "awaiting_approval",
            "commit_message", "final_summary", "messages", "typed_messages",
            "awaiting_user_input", "user_input_prompt", "pr_url", "pr_number",
        }

        missing = placeholders - valid_state_keys
        assert not missing, f"System prompt uses {{key}} placeholders not in session state: {missing}"

