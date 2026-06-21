"""Core events - streamed back from the engine."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Event:
    """Base event class. All events inherit from this."""

    job_id: str


@dataclass(frozen=True)
class Started(Event):
    """Job started."""

    kind: str  # Type of command that started this job


@dataclass(frozen=True)
class Progress(Event):
    """Job progress update."""

    phase: str
    message: str
    pct: float | None = None  # Optional progress percentage


@dataclass(frozen=True)
class Message(Event):
    """A message turn (for brainstorm/ask sessions)."""

    role: str  # "assistant"
    text: str
    citations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Result(Event):
    """Job completed (success or failure)."""

    ok: bool
    payload: dict = field(default_factory=dict)
