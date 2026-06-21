"""Core commands - all user actions flow through these."""

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class Command:
    """Base command class. All commands inherit from this."""

    user: str  # CLI user or Slack user ID


@dataclass(frozen=True)
class Ask(Command):
    """One-shot cited Q&A over the knowledge base."""

    query: str


@dataclass(frozen=True)
class Brainstorm(Command):
    """Interactive multi-turn brainstorming session."""

    text: str
    session_id: str | None = None


@dataclass(frozen=True)
class ShowInterests(Command):
    """Show current interest model."""

    view: Literal["show", "timeline"] = "show"


@dataclass(frozen=True)
class ResearchTopic(Command):
    """Manually trigger the Research Agent for a topic."""

    topic: str
    depth: Literal["shallow", "normal", "deep"] = "normal"


@dataclass(frozen=True)
class ShowGraph(Command):
    """View citation or knowledge graph."""

    kind: Literal["knowledge", "citation"] = "knowledge"
    topic: str | None = None


@dataclass(frozen=True)
class Opportunities(Command):
    """List, save, or dismiss opportunities."""

    action: Literal["list", "save", "dismiss"] = "list"
    ref: str | None = None


@dataclass(frozen=True)
class ShowDigest(Command):
    """Show insight digest for a date."""

    date: str | None = None


@dataclass(frozen=True)
class Feedback(Command):
    """Provide feedback on a recommendation or answer."""

    ref: str  # opportunity/answer ID
    verdict: Literal["accept", "reject", "correct"]
    note: str | None = None


@dataclass(frozen=True)
class IngestNow(Command):
    """Trigger activity sensing now."""

    connector: str | None = None  # All enabled if None


@dataclass(frozen=True)
class JobStatus(Command):
    """Check job status."""

    job_id: str | None = None


@dataclass(frozen=True)
class Cancel(Command):
    """Cancel a running job."""

    job_id: str


@dataclass(frozen=True)
class SetPref(Command):
    """Set a user preference."""

    key: str
    value: str


@dataclass(frozen=True)
class Topics(Command):
    """Manage tracked topics."""

    action: Literal["add", "list", "rm"]
    name: str | None = None


@dataclass(frozen=True)
class Sources(Command):
    """Manage connectors."""

    action: Literal["add", "list", "rm"]
    name: str | None = None
