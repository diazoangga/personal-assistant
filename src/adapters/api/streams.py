"""Streaming endpoints: per-job event streams over SSE and WebSocket.

Both read from the EventHub, which buffers a job's events from creation, so a
client may connect any time after the POST returns and still see the full
history followed by live updates until the terminal `result`.
"""

from __future__ import annotations

import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from .deps import get_hub, require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["streams"])


@router.get("/events/{job_id}", dependencies=[Depends(require_auth)])
async def stream_events_sse(job_id: str) -> StreamingResponse:
    """Stream a job's events as Server-Sent Events."""
    hub = get_hub()

    async def gen() -> AsyncGenerator[str, None]:
        if hub.get(job_id) is None:
            yield f"data: {json.dumps({'event_type': 'error', 'job_id': job_id, 'payload': {'message': 'unknown job'}})}\n\n"
            return
        async for event in hub.stream(job_id):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.websocket("/ws/events/{job_id}")
async def stream_events_ws(websocket: WebSocket, job_id: str) -> None:
    """Stream a job's events over a WebSocket (preferred for live updates)."""
    await websocket.accept()
    hub = get_hub()
    try:
        if hub.get(job_id) is None:
            await websocket.send_json(
                {"event_type": "error", "job_id": job_id, "payload": {"message": "unknown job"}}
            )
            return
        async for event in hub.stream(job_id):
            await websocket.send_json(event)
    except WebSocketDisconnect:
        logger.debug("ws client disconnected for job %s", job_id)
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("ws error for job %s: %s", job_id, exc)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
