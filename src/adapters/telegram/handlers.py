"""FastAPI handlers for Telegram Mini App API."""

import asyncio
import json
import logging
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse

from ...core.commands import Ask, Brainstorm, Feedback, ResearchTopic, ShowGraph, ShowInterests
from ...core.events import Event, Message, Progress, Result, Started
from ...main_engine import PersonalAssistantEngine
from .auth import TelegramInitDataValidator
from .models import (
    AskRequest,
    BrainstormRequest,
    EventUpdate,
    FeedbackRequest,
    HealthResponse,
    ResearchRequest,
    ShowGraphRequest,
    ShowInterestsRequest,
    TelegramUser,
    UserInfo,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["telegram"])


class TelegramDependencies:
    """Dependency injection for Telegram auth and engine."""

    def __init__(self, engine: PersonalAssistantEngine, bot_token: str):
        self.engine = engine
        self.validator = TelegramInitDataValidator(bot_token)

    async def authenticate(self, init_data: str) -> TelegramUser:
        """Validate initData and return authenticated user.

        Falls back to an anonymous user when initData is missing or fails
        validation (e.g. testing outside a real Telegram client) instead of
        hard-blocking, since commands should still work during dev/testing.
        """
        if not init_data:
            return TelegramUser(user_id="anonymous")

        params = self.validator.validate(init_data)
        if not params:
            logger.warning("initData failed validation, falling back to anonymous user")
            return TelegramUser(user_id="anonymous")

        user_id = self.validator.extract_user_id(params)
        if not user_id:
            logger.warning("Could not extract user ID from initData, falling back to anonymous user")
            return TelegramUser(user_id="anonymous")

        # TODO: Parse first_name, is_premium from params if needed
        return TelegramUser(user_id=user_id)


# Global dependency
_deps: Optional[TelegramDependencies] = None


def set_dependencies(engine: PersonalAssistantEngine, bot_token: str) -> None:
    """Initialize dependencies (call from app startup)."""
    global _deps
    _deps = TelegramDependencies(engine, bot_token)


def get_deps() -> TelegramDependencies:
    """Get the dependency injector."""
    if _deps is None:
        raise RuntimeError("Dependencies not initialized")
    return _deps


async def get_user(
    x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
    deps: TelegramDependencies = Depends(get_deps),
) -> TelegramUser:
    """Dependency to extract and validate authenticated user.

    Reads initData from a header (not the body) so it never collides with
    each route's own JSON request body.
    """
    return await deps.authenticate(x_telegram_init_data)


# Routes


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(status="ok", version="0.1.0")


@router.post("/auth", response_model=UserInfo)
async def authenticate(user: TelegramUser = Depends(get_user)) -> UserInfo:
    """Authenticate and return user info."""
    return UserInfo(
        user_id=user.user_id,
        first_name=user.first_name,
        is_premium=user.is_premium,
    )


@router.post("/ask")
async def ask_handler(
    request: AskRequest,
    user: TelegramUser = Depends(get_user),
    deps: TelegramDependencies = Depends(get_deps),
) -> dict[str, str]:
    """Submit an Ask command and return job ID."""
    cmd = Ask(user=user.to_command_user_field(), query=request.query)
    job_id = await deps.engine.submit(cmd)
    return {"job_id": job_id, "kind": "ask"}


@router.post("/brainstorm")
async def brainstorm_handler(
    request: BrainstormRequest,
    user: TelegramUser = Depends(get_user),
    deps: TelegramDependencies = Depends(get_deps),
) -> dict[str, str]:
    """Submit a Brainstorm command and return job ID."""
    cmd = Brainstorm(user=user.to_command_user_field(), text=request.text, session_id=request.session_id)
    job_id = await deps.engine.submit(cmd)
    return {"job_id": job_id, "kind": "brainstorm"}


@router.post("/research")
async def research_handler(
    request: ResearchRequest,
    user: TelegramUser = Depends(get_user),
    deps: TelegramDependencies = Depends(get_deps),
) -> dict[str, str]:
    """Submit a ResearchTopic command and return job ID."""
    cmd = ResearchTopic(user=user.to_command_user_field(), topic=request.topic, depth=request.depth)
    job_id = await deps.engine.submit(cmd)
    return {"job_id": job_id, "kind": "research"}


@router.post("/feedback")
async def feedback_handler(
    request: FeedbackRequest,
    user: TelegramUser = Depends(get_user),
    deps: TelegramDependencies = Depends(get_deps),
) -> dict[str, str]:
    """Submit feedback on a recommendation or answer."""
    cmd = Feedback(
        user=user.to_command_user_field(),
        ref=request.ref,
        verdict=request.verdict,
        note=request.note,
    )
    job_id = await deps.engine.submit(cmd)
    return {"job_id": job_id, "kind": "feedback"}


@router.post("/graph")
async def graph_handler(
    request: ShowGraphRequest,
    user: TelegramUser = Depends(get_user),
    deps: TelegramDependencies = Depends(get_deps),
) -> dict[str, str]:
    """Request a citation or knowledge graph."""
    cmd = ShowGraph(user=user.to_command_user_field(), kind=request.kind, topic=request.topic)
    job_id = await deps.engine.submit(cmd)
    return {"job_id": job_id, "kind": "show_graph"}


@router.post("/interests")
async def interests_handler(
    request: ShowInterestsRequest,
    user: TelegramUser = Depends(get_user),
    deps: TelegramDependencies = Depends(get_deps),
) -> dict[str, str]:
    """Request user's interests."""
    cmd = ShowInterests(user=user.to_command_user_field(), view="show")
    job_id = await deps.engine.submit(cmd)
    return {"job_id": job_id, "kind": "show_interests"}


@router.get("/events/{job_id}")
async def stream_events(
    job_id: str,
    user: TelegramUser = Depends(get_user),
    deps: TelegramDependencies = Depends(get_deps),
) -> StreamingResponse:
    """Stream job events via Server-Sent Events (SSE)."""

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events from the job's event stream."""
        try:
            async for event in deps.engine.bus.subscribe(job_id):
                # Convert event to JSON
                event_data = _event_to_dict(event)

                # SSE format: "data: {json}\n\n"
                yield f"data: {json.dumps(event_data)}\n\n"

                # Stop after Result
                if isinstance(event, Result):
                    break
        except Exception as e:
            logger.error(f"Error streaming events for job {job_id}: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.websocket("/ws/events/{job_id}")
async def websocket_events(
    websocket: WebSocket,
    job_id: str,
    user: TelegramUser = Depends(get_user),
    deps: TelegramDependencies = Depends(get_deps),
) -> None:
    """Stream job events via WebSocket (preferred for live updates)."""
    await websocket.accept()

    try:
        async for event in deps.engine.bus.subscribe(job_id):
            event_data = _event_to_dict(event)
            await websocket.send_json(event_data)

            if isinstance(event, Result):
                break
    except WebSocketDisconnect:
        logger.debug(f"WebSocket disconnected for job {job_id}")
    except Exception as e:
        logger.error(f"Error in WebSocket for job {job_id}: {e}")
        try:
            await websocket.send_json({"event_type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# Helper functions


def _event_to_dict(event: Event) -> dict:
    """Convert an Event object to a dictionary for JSON serialization."""
    if isinstance(event, Started):
        return {
            "event_type": "started",
            "job_id": event.job_id,
            "payload": {"kind": event.kind},
        }
    elif isinstance(event, Progress):
        return {
            "event_type": "progress",
            "job_id": event.job_id,
            "payload": {
                "phase": event.phase,
                "message": event.message,
                "pct": event.pct,
            },
        }
    elif isinstance(event, Message):
        return {
            "event_type": "message",
            "job_id": event.job_id,
            "payload": {
                "role": event.role,
                "text": event.text,
                "citations": event.citations,
            },
        }
    elif isinstance(event, Result):
        return {
            "event_type": "result",
            "job_id": event.job_id,
            "payload": {
                "ok": event.ok,
                "data": event.payload,
            },
        }
    else:
        return {
            "event_type": "unknown",
            "job_id": event.job_id,
            "payload": {},
        }
