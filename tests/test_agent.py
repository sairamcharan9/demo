"""Tests for agent/agent.py — agent creation and tool registration."""

import os

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.agent import create_agent, ALL_TOOLS, SYSTEM_PROMPT

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
        assert len(agent.tools) == 25

    def test_has_instruction(self):
        agent = create_agent()
        assert agent.instruction is not None
        assert len(agent.instruction) > 100

    def test_has_description(self):
        agent = create_agent()
        assert agent.description is not None


class TestAllTools:
    def test_tool_count(self):
        assert len(ALL_TOOLS) == 25

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
