"""Pydantic models for Telegram Mini App API requests/responses."""

from dataclasses import dataclass
from typing import Any, Optional

from pydantic import BaseModel, Field


# Command Request Models
class AskRequest(BaseModel):
    """Request to ask a question."""

    query: str = Field(..., description="Question to ask")
    session_id: Optional[str] = Field(None, description="Optional session ID for conversation")


class BrainstormRequest(BaseModel):
    """Request to brainstorm on a topic."""

    text: str = Field(..., description="Text to brainstorm or continue brainstorming")
    session_id: Optional[str] = Field(None, description="Session ID for multi-turn brainstorm")


class ResearchRequest(BaseModel):
    """Request to research a topic."""

    topic: str = Field(..., description="Topic to research")
    depth: str = Field("normal", description="Research depth: shallow, normal, or deep")


class FeedbackRequest(BaseModel):
    """Feedback on a recommendation or answer."""

    ref: str = Field(..., description="Reference ID of the item being rated")
    verdict: str = Field(..., description="accept, reject, or correct")
    note: Optional[str] = Field(None, description="Optional note with feedback")


class ShowGraphRequest(BaseModel):
    """Request to fetch a knowledge/citation graph."""

    kind: str = Field("knowledge", description="Graph type: knowledge or citation")
    topic: Optional[str] = Field(None, description="Topic to filter graph (optional)")


class ShowInterestsRequest(BaseModel):
    """Request to fetch interests."""

    min_strength: float = Field(0.0, description="Minimum interest strength to return")


class AddInterestRequest(BaseModel):
    """Request to manually add an interest."""

    label: str = Field(..., description="Interest label")
    strength: float = Field(0.5, description="Initial strength (0.0-1.0)")


# Response Models
class JobStarted(BaseModel):
    """Response when a job is submitted."""

    job_id: str = Field(..., description="Job ID for tracking")
    kind: str = Field(..., description="Type of job (ask, brainstorm, research, etc.)")


class EventUpdate(BaseModel):
    """Event streaming update (sent via WebSocket)."""

    event_type: str = Field(..., description="Type: started, progress, message, result")
    job_id: str = Field(..., description="Associated job ID")
    payload: dict[str, Any] = Field(default_factory=dict, description="Event-specific data")


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field("ok", description="Status: ok or error")
    version: str = Field(..., description="API version")


class UserInfo(BaseModel):
    """Authenticated user info."""

    user_id: str = Field(..., description="Telegram user ID")
    first_name: Optional[str] = Field(None, description="Telegram first name")
    is_premium: bool = Field(False, description="Is Telegram Premium subscriber")


class GraphData(BaseModel):
    """Citation or knowledge graph data."""

    nodes: list[dict[str, Any]] = Field(default_factory=list, description="Graph nodes")
    edges: list[dict[str, Any]] = Field(default_factory=list, description="Graph edges")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Graph metadata (topic, count, etc.)"
    )


class InterestItem(BaseModel):
    """User interest."""

    id: str = Field(..., description="Interest ID")
    label: str = Field(..., description="Interest label")
    strength: float = Field(..., description="Current strength (0.0-1.0)")
    last_updated: str = Field(..., description="ISO timestamp of last update")


@dataclass
class TelegramUser:
    """Authenticated Telegram user."""

    user_id: str
    first_name: Optional[str] = None
    is_premium: bool = False

    def to_command_user_field(self) -> str:
        """Return the user identifier for engine.submit(cmd)."""
        return f"telegram:{self.user_id}"
