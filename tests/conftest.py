"""Shared Pytest fixtures for Forge tests."""

import pytest
import os

class MockWorkspace:
    def __init__(self):
        # Use current working directory so subprocess calls don't fail with WinError 267
        self.path = os.getcwd()

class MockToolContext:
    """A minimal mock for google.adk.tools.ToolContext."""
    
    def __init__(self, state: dict | None = None):
        self.state = state if state is not None else {}
        self.workspace = MockWorkspace()
        self.session_id = "test-session-1234"
