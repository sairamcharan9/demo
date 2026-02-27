"""
Memory — Session and memory service factory.

Dual-mode:
  - "dev"  → InMemorySessionService + InMemoryMemoryService (local, no GCP)
  - "prod" → VertexAiSessionService + VertexAiMemoryBankService (Firestore-backed)

The mode is determined by the SERVICE_MODE env var (default: "dev").
"""

import os
from typing import Optional

from google.adk.sessions import (
    InMemorySessionService,
    VertexAiSessionService,
)
from google.adk.memory import (
    BaseMemoryService,
    InMemoryMemoryService,
    VertexAiMemoryBankService,
)


def create_session_service(mode: str | None = None):
    """Create the appropriate session service.

    Args:
        mode: "dev" or "prod". Defaults to SERVICE_MODE env var or "dev".

    Returns:
        InMemorySessionService for dev, VertexAiSessionService for prod.
    """
    mode = mode or os.environ.get("SERVICE_MODE", "dev")

    if mode == "prod":
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
        agent_engine_id = os.environ.get("AGENT_ENGINE_ID")

        if not project:
            raise ValueError("GOOGLE_CLOUD_PROJECT env var required for prod mode")

        return VertexAiSessionService(
            project=project,
            location=location,
            agent_engine_id=agent_engine_id,
        )

    return InMemorySessionService()


def create_memory_service(mode: str | None = None) -> Optional[BaseMemoryService]:
    """Create the appropriate memory service.

    Args:
        mode: "dev" or "prod". Defaults to SERVICE_MODE env var or "dev".

    Returns:
        InMemoryMemoryService for dev, VertexAiMemoryBankService for prod.
    """
    mode = mode or os.environ.get("SERVICE_MODE", "dev")

    if mode == "prod":
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

        if not project:
            raise ValueError("GOOGLE_CLOUD_PROJECT env var required for prod mode")

        return VertexAiMemoryBankService(
            project=project,
            location=location,
        )

    return InMemoryMemoryService()


def create_services(mode: str | None = None):
    """Create both session and memory services.

    Returns:
        Tuple of (session_service, memory_service).
    """
    mode = mode or os.environ.get("SERVICE_MODE", "dev")
    return create_session_service(mode), create_memory_service(mode)
