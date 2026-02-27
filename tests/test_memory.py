"""Tests for memory/vertex_memory.py — service factory."""

import os

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memory.vertex_memory import (
    create_session_service,
    create_memory_service,
    create_services,
)

from google.adk.sessions import InMemorySessionService
from google.adk.memory import InMemoryMemoryService

import pytest


class TestCreateSessionService:
    def test_dev_mode_default(self, monkeypatch):
        monkeypatch.delenv("SERVICE_MODE", raising=False)
        service = create_session_service()
        assert isinstance(service, InMemorySessionService)

    def test_dev_mode_explicit(self):
        service = create_session_service(mode="dev")
        assert isinstance(service, InMemorySessionService)

    def test_prod_mode_missing_project(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        with pytest.raises(ValueError, match="GOOGLE_CLOUD_PROJECT"):
            create_session_service(mode="prod")


class TestCreateMemoryService:
    def test_dev_mode_default(self, monkeypatch):
        monkeypatch.delenv("SERVICE_MODE", raising=False)
        service = create_memory_service()
        assert isinstance(service, InMemoryMemoryService)

    def test_dev_mode_explicit(self):
        service = create_memory_service(mode="dev")
        assert isinstance(service, InMemoryMemoryService)

    def test_prod_mode_missing_project(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        with pytest.raises(ValueError, match="GOOGLE_CLOUD_PROJECT"):
            create_memory_service(mode="prod")


class TestCreateServices:
    def test_returns_tuple(self, monkeypatch):
        monkeypatch.delenv("SERVICE_MODE", raising=False)
        session_svc, memory_svc = create_services()
        assert isinstance(session_svc, InMemorySessionService)
        assert isinstance(memory_svc, InMemoryMemoryService)

    def test_mode_from_env(self, monkeypatch):
        monkeypatch.setenv("SERVICE_MODE", "dev")
        session_svc, memory_svc = create_services()
        assert isinstance(session_svc, InMemorySessionService)
