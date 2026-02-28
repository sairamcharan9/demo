"""Shared test fixtures for Forge tool tests."""

import os
import sys

# Ensure project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class MockToolContext:
    """Minimal stand-in for ADK ToolContext during testing.

    Mirrors the `tool_context.state` dict interface that all tools use
    for reading/writing session state. ADK's real ToolContext provides
    `.state`, `.search_memory()`, `.list_artifacts()`, etc.
    """

    def __init__(self, state: dict | None = None):
        self.state = state if state is not None else {}
