"""Shared dependencies for the local web API.

Holds the process-wide engine, event hub, daemon handle, and config; provides
FastAPI dependency callables and an optional bearer-token guard.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Header, HTTPException, status

from ...main_engine import PersonalAssistantEngine
from ...store.knowledge import UnifiedKnowledgeStore
from .hub import EventHub


class _State:
    engine: Optional[PersonalAssistantEngine] = None
    hub: Optional[EventHub] = None
    daemon: Optional[Any] = None  # PersonalAssistantDaemon (avoid import cycle)
    config: dict[str, Any] = {}
    token: Optional[str] = None
    user: str = "local"


_state = _State()


def set_dependencies(
    *,
    engine: PersonalAssistantEngine,
    hub: EventHub,
    daemon: Any,
    config: dict[str, Any],
    token: Optional[str],
    user: str,
) -> None:
    _state.engine = engine
    _state.hub = hub
    _state.daemon = daemon
    _state.config = config
    _state.token = token or None
    _state.user = user or "local"


def get_engine() -> PersonalAssistantEngine:
    if _state.engine is None:
        raise RuntimeError("API dependencies not initialized")
    return _state.engine


def get_store() -> UnifiedKnowledgeStore:
    return get_engine().store


def get_hub() -> EventHub:
    if _state.hub is None:
        raise RuntimeError("API dependencies not initialized")
    return _state.hub


def get_daemon() -> Any:
    return _state.daemon


def get_config() -> dict[str, Any]:
    return _state.config


def get_user() -> str:
    return _state.user


async def require_auth(authorization: Optional[str] = Header(default=None)) -> None:
    """Optional bearer guard. No-op unless LOCAL_API_TOKEN is configured."""
    if not _state.token:
        return
    if authorization != f"Bearer {_state.token}":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid bearer token",
        )
