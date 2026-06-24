"""Pydantic request/response models for the local web API."""

from __future__ import annotations

from typing import Any, Optional, Union

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Command requests (POST → job)
# --------------------------------------------------------------------------- #
class AskRequest(BaseModel):
    query: str = Field(..., description="Question to ask")
    session_id: Optional[str] = Field(None, description="Conversation/session id to append to")


class BrainstormRequest(BaseModel):
    text: str = Field(..., description="Topic or prompt to brainstorm")
    session_id: Optional[str] = Field(None, description="Session id (reserved; one-shot for now)")


class ResearchRequest(BaseModel):
    topic: str = Field(..., description="Topic to research")
    depth: Union[int, str] = Field(
        "normal",
        description="shallow|normal|deep, or an int 1-5 (1-2=shallow, 3=normal, 4-5=deep)",
    )


class FeedbackRequest(BaseModel):
    ref: str = Field(..., description="Reference id of the item being rated")
    verdict: str = Field(..., description="accept | reject | correct")
    note: Optional[str] = Field(None, description="Optional free-text note")


# --------------------------------------------------------------------------- #
# Responses
# --------------------------------------------------------------------------- #
class JobStarted(BaseModel):
    job_id: str = Field(..., description="Stream this id via /events or /ws/events")
    kind: str = Field(..., description="ask | brainstorm | research | feedback")


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = Field(..., description="API version")


class DaemonStatus(BaseModel):
    running: bool
    pid: Optional[int] = None
    last_ingest: Optional[str] = None


class EventUpdate(BaseModel):
    """Documentation of the streamed envelope (events are sent as raw JSON)."""

    event_type: str
    job_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
