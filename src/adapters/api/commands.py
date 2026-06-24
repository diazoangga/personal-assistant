"""Command endpoints: POST a command, get a job_id, stream the result.

ask / brainstorm / research drive the engine's public coroutines (which carry
the conversation-tracking and knowledge-storage side effects). feedback is
persisted to the activity_log. Each endpoint registers a job in the hub *before*
starting work, then returns immediately.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from . import hub as hub_mod
from .deps import get_engine, get_hub, get_store, get_user, require_auth
from .models import (
    AskRequest,
    BrainstormRequest,
    FeedbackRequest,
    JobStarted,
    ResearchRequest,
)

router = APIRouter(prefix="/api", tags=["commands"], dependencies=[Depends(require_auth)])


def _normalize_depth(depth) -> int:
    """Map the API depth (str enum or int 1-5) to the engine's int depth (1-3)."""
    if isinstance(depth, str):
        return {"shallow": 1, "normal": 2, "deep": 3}.get(depth.lower().strip(), 2)
    try:
        d = int(depth)
    except (TypeError, ValueError):
        return 2
    if d <= 2:
        return 1
    if d == 3:
        return 2
    return 3


@router.post("/ask", response_model=JobStarted)
async def ask(req: AskRequest) -> JobStarted:
    engine = get_engine()
    hub = get_hub()
    user = get_user()
    # Ensure a stable session id so the desktop "Sessions" view can group turns.
    session_id = req.session_id or f"{user}-{uuid.uuid4().hex[:8]}"

    rec = hub.create("ask")
    coro = engine.ask(req.query, user=user, session_id=session_id)

    async def _extra() -> dict:
        return {"session_id": session_id}

    asyncio.create_task(
        hub_mod.run_text_job(hub, rec.job_id, "ask", coro, result_extra=_extra)
    )
    return JobStarted(job_id=rec.job_id, kind="ask")


@router.post("/brainstorm", response_model=JobStarted)
async def brainstorm(req: BrainstormRequest) -> JobStarted:
    engine = get_engine()
    hub = get_hub()
    user = get_user()

    rec = hub.create("brainstorm")
    coro = engine.brainstorm(req.text, user=user)
    asyncio.create_task(hub_mod.run_text_job(hub, rec.job_id, "brainstorm", coro))
    return JobStarted(job_id=rec.job_id, kind="brainstorm")


@router.post("/research", response_model=JobStarted)
async def research(req: ResearchRequest) -> JobStarted:
    engine = get_engine()
    hub = get_hub()
    store = get_store()
    user = get_user()
    topic = req.topic
    depth = _normalize_depth(req.depth)

    rec = hub.create("research")
    coro = engine.research(topic, depth=depth, user=user)

    async def _extra() -> dict:
        runs = await store.get_research_runs(topic=topic, limit=1)
        if not runs:
            return {}
        r = runs[0]
        return {
            k: r.get(k)
            for k in (
                "papers_found",
                "papers_new",
                "concepts_extracted",
                "concepts_new",
                "relationships_found",
                "run_id",
            )
            if k in r
        }

    asyncio.create_task(
        hub_mod.run_text_job(hub, rec.job_id, "research", coro, result_extra=_extra)
    )
    return JobStarted(job_id=rec.job_id, kind="research")


@router.post("/feedback", response_model=JobStarted)
async def feedback(req: FeedbackRequest) -> JobStarted:
    """Record feedback. Persisted to activity_log (no dedicated feedback table)."""
    hub = get_hub()
    store = get_store()
    rec = hub.create("feedback")

    async def _do() -> str:
        # execute_query does not commit; use the connection directly for the write.
        await store._db.execute(
            "INSERT INTO activity_log (timestamp, activity_type, description, raw_data) "
            "VALUES (?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                "feedback",
                f"{req.verdict} on {req.ref}",
                json.dumps({"ref": req.ref, "verdict": req.verdict, "note": req.note}),
            ),
        )
        await store._db.commit()
        return f"Recorded '{req.verdict}' feedback on {req.ref}."

    asyncio.create_task(hub_mod.run_text_job(hub, rec.job_id, "feedback", _do()))
    return JobStarted(job_id=rec.job_id, kind="feedback")
