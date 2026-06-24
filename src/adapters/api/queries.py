"""Query endpoints: synchronous dashboard reads straight from the store.

These power the desktop app's panels (stats, interests, graph, knowledge,
sessions, activity, daemon status). They read committed state and return JSON
immediately — no jobs, no streaming.

All access goes through the store's ``_db`` abstraction
(``fetchall``/``fetchone``/``execute``) against the PostgreSQL backend selected by
``DB_TYPE``. The ``?`` placeholders are rewritten to ``$n`` by the PostgreSQL
connection wrapper.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .deps import get_daemon, get_store, require_auth
from .models import DaemonStatus, HealthResponse

router = APIRouter(prefix="/api", tags=["queries"], dependencies=[Depends(require_auth)])

API_VERSION = "0.1.0"


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", version=API_VERSION)


@router.get("/daemon/status", response_model=DaemonStatus)
async def daemon_status() -> DaemonStatus:
    daemon = get_daemon()
    running = bool(daemon is not None and getattr(daemon, "running", False))
    last = getattr(daemon, "_last_ingest", None)
    last_ingest = last.isoformat() if last is not None else None
    return DaemonStatus(running=running, pid=os.getpid() if running else None, last_ingest=last_ingest)


@router.get("/stats")
async def stats() -> dict[str, Any]:
    store = get_store()
    data: dict[str, Any] = dict(await store.get_stats())
    ke = await store._db.fetchone("SELECT COUNT(*) AS c FROM knowledge_entries")
    data["knowledge_entries"] = ke["c"] if ke else 0
    questions = await store._db.fetchone(
        "SELECT COALESCE(SUM(total_questions), 0) AS q FROM user_stats"
    )
    data["total_questions"] = questions["q"] if questions else 0
    return data


@router.get("/interests")
async def interests(min_strength: float = Query(0.0, ge=0.0, le=1.0)) -> list[dict[str, Any]]:
    return await get_store().get_interests(min_strength=min_strength)


@router.get("/interests/{label}/timeline")
async def interest_timeline(
    label: str, limit: int = Query(50, ge=1, le=500)
) -> list[dict[str, Any]]:
    return await get_store()._db.fetchall(
        "SELECT signal_id, topic, confidence, timestamp FROM interest_signal_evidence "
        "WHERE topic = ? ORDER BY timestamp DESC LIMIT ?",
        (label, limit),
    )


@router.get("/knowledge")
async def knowledge(
    min_quality: float = Query(0.65, ge=0.0, le=1.0),
    limit: int = Query(50, ge=1, le=500),
) -> list[dict[str, Any]]:
    return await get_store().get_knowledge_entries(min_quality=min_quality, limit=limit)


@router.get("/knowledge/search")
async def knowledge_search(
    q: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=200)
) -> list[dict[str, Any]]:
    return await get_store().search_knowledge_entries(q, limit=limit)


@router.get("/graph/subgraph")
async def graph_subgraph(
    topic: Optional[str] = Query(None), depth: int = Query(2, ge=1, le=4)
) -> dict[str, Any]:
    nodes, edges = await get_store().relevant_subgraphs(
        interests=[topic] if topic else None, max_depth=depth
    )
    return {"nodes": nodes, "edges": edges}


@router.get("/citations/{citation_id}")
async def citation(citation_id: str) -> dict[str, Any]:
    store = get_store()
    cit = await store.get_citation(citation_id)
    if cit is None:
        raise HTTPException(status_code=404, detail="Citation not found")
    cit = dict(cit)
    cit["linked_concepts"] = await store.get_linked_concepts_for_citation(citation_id)
    return cit


@router.get("/research/runs")
async def research_runs(
    topic: Optional[str] = Query(None), limit: int = Query(20, ge=1, le=200)
) -> list[dict[str, Any]]:
    return await get_store().get_research_runs(topic=topic, limit=limit)


@router.get("/sessions")
async def sessions(limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
    return await get_store()._db.fetchall(
        "SELECT * FROM conversation_sessions ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    )


@router.get("/sessions/{session_id}/turns")
async def session_turns(
    session_id: str, limit: int = Query(200, ge=1, le=1000)
) -> list[dict[str, Any]]:
    return await get_store().get_conversation_history(session_id, limit=limit)


@router.get("/activity")
async def activity(limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
    return await get_store()._db.fetchall(
        "SELECT id, timestamp, activity_type, description, raw_data "
        "FROM activity_log ORDER BY id DESC LIMIT ?",
        (limit,),
    )
