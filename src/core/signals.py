"""Interest signal and classification data models."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class InterestSignal:
    """A signal classified into interests/topics."""

    activity_signal_id: str  # points back to original signal
    topics: list[str]  # ["machine learning", "python"]
    confidences: list[float]  # [0.8, 0.6] matching topics
    source: str  # "github", "browser", "slack", "vscode"
    timestamp: datetime
    user_id: str = "local"
    explanation: str = ""  # why we classified it this way

    def __post_init__(self):
        """Validate topics and confidences match."""
        if len(self.topics) != len(self.confidences):
            raise ValueError("topics and confidences must have same length")
        if not all(0.0 <= c <= 1.0 for c in self.confidences):
            raise ValueError("confidences must be 0-1")

    def top_topic(self) -> tuple[str | None, float]:
        """Return highest confidence topic and confidence."""
        if not self.topics:
            return None, 0.0
        idx = self.confidences.index(max(self.confidences))
        return self.topics[idx], self.confidences[idx]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for storage."""
        return {
            "activity_signal_id": self.activity_signal_id,
            "topics": self.topics,
            "confidences": self.confidences,
            "source": self.source,
            "timestamp": self.timestamp.isoformat(),
            "user_id": self.user_id,
            "explanation": self.explanation,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InterestSignal":
        """Construct from dict."""
        return cls(
            activity_signal_id=data["activity_signal_id"],
            topics=data["topics"],
            confidences=data["confidences"],
            source=data["source"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            user_id=data.get("user_id", "local"),
            explanation=data.get("explanation", ""),
        )


@dataclass
class InterestClassification:
    """Result of classifying a single activity signal."""

    signal_id: str
    topics: list[str]
    confidences: list[float]
    explanation: str  # why we classified it this way
    model_version: str  # for tracking model changes
    timestamp: datetime = field(default_factory=datetime.utcnow)  # original signal time
    error: str | None = None  # if classification failed

    def is_valid(self) -> bool:
        """Check if classification succeeded."""
        return self.error is None and len(self.topics) > 0


@dataclass
class StrengthSnapshot:
    """Snapshot of interest strength at a point in time."""

    user_id: str
    topic: str
    strength: float  # 0-1
    timestamp: datetime
    signal_count: int  # how many signals support this
    confidence: float  # average confidence of signals
    decay_hours: int = 720  # decay window used for calculation


@dataclass
class StrengthChange:
    """A detected change in interest strength."""

    topic: str
    old_strength: float
    new_strength: float
    strength_delta: float  # new - old
    percentage_increase: float  # (new - old) / old * 100
    triggering_signal: str  # which signal triggered the change
    timestamp: datetime = field(default_factory=datetime.now)

    def should_trigger_research(self, threshold: float = 0.1) -> bool:
        """Check if this change meets research trigger threshold."""
        return self.strength_delta >= threshold
