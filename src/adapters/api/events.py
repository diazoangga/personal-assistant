"""Event envelope helpers.

Every streamed event shares one JSON envelope so the desktop client can parse
all of them uniformly:

    { "event_type": <str>, "job_id": <str>, "payload": { ... } }

These builders produce that envelope. The shapes match docs/WEB_API.md §3 and the
event types in src/core/events.py.
"""

from __future__ import annotations

from typing import Any, Optional

from ...core.events import Event, Message, Progress, Result, Started


def started(job_id: str, kind: str) -> dict[str, Any]:
    return {"event_type": "started", "job_id": job_id, "payload": {"kind": kind}}


def progress(
    job_id: str, phase: str, message: str, pct: Optional[float] = None
) -> dict[str, Any]:
    return {
        "event_type": "progress",
        "job_id": job_id,
        "payload": {"phase": phase, "message": message, "pct": pct},
    }


def message(
    job_id: str, text: str, citations: Optional[list[str]] = None, role: str = "assistant"
) -> dict[str, Any]:
    return {
        "event_type": "message",
        "job_id": job_id,
        "payload": {"role": role, "text": text, "citations": citations or []},
    }


def result(job_id: str, ok: bool, data: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    return {
        "event_type": "result",
        "job_id": job_id,
        "payload": {"ok": ok, "data": data or {}},
    }


def error(job_id: str, message: str) -> dict[str, Any]:
    return {"event_type": "error", "job_id": job_id, "payload": {"message": message}}


def event_to_dict(event: Event) -> dict[str, Any]:
    """Serialize a core Event into the wire envelope.

    Used when piping events published on the engine's EventBus (e.g. by command
    handlers) into the API's event hub.
    """
    if isinstance(event, Started):
        return started(event.job_id, event.kind)
    if isinstance(event, Progress):
        return progress(event.job_id, event.phase, event.message, event.pct)
    if isinstance(event, Message):
        return message(event.job_id, event.text, event.citations, event.role)
    if isinstance(event, Result):
        return result(event.job_id, event.ok, event.payload)
    return {"event_type": "unknown", "job_id": getattr(event, "job_id", ""), "payload": {}}
