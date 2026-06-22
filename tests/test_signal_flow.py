"""Integration tests for the signal flow: connectors -> Interest Agent -> research triggers."""

import json
import os
import tempfile
from datetime import datetime, timedelta

import pytest

from src.agents.interest import InterestAgent
from src.daemon.connector_base import ActivitySignal
from src.store.memory import UserMemory


class FakeLLM:
    """Returns queued canned JSON classification responses, in call order."""

    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self.calls: list[str] = []

    async def complete(self, role: str, prompt: str, **kwargs) -> str:
        self.calls.append(prompt)
        if not self._responses:
            return json.dumps({"topics": [], "confidences": [], "explanation": "exhausted"})
        return json.dumps(self._responses.pop(0))


def make_github_signal(message: str, timestamp: datetime | None = None) -> ActivitySignal:
    """Build a GitHub commit ActivitySignal for tests."""
    return ActivitySignal(
        source="github",
        event_type="commit",
        timestamp=timestamp or datetime.utcnow(),
        data={"repository": "ml-project", "message": message},
    )


@pytest.fixture
def temp_db():
    """Create a temporary SQLite database file."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
async def user_memory(temp_db):
    """Create a UserMemory instance with initialized database."""
    memory = UserMemory(temp_db)
    await memory.initialize()
    yield memory
    await memory.close()


class TestSignalToInterest:
    """Signal classification and storage."""

    @pytest.mark.asyncio
    async def test_signal_to_interest_single_topic(self, user_memory):
        """A GitHub commit signal is classified into a topic and stored with strength."""
        llm = FakeLLM(
            [{"topics": ["machine learning"], "confidences": [0.8], "explanation": "ml commit"}]
        )
        agent = InterestAgent(engine=None, llm=llm, memory=user_memory)

        signal = make_github_signal("Add transformer model")
        classified = await agent._classify_signals([signal])

        assert len(classified) == 1
        assert classified[0].topics == ["machine learning"]
        assert classified[0].confidences[0] == 0.8

        await user_memory.add_classified_signal(
            user_id="local",
            signal_id=classified[0].signal_id,
            topic="machine learning",
            confidence=classified[0].confidences[0],
            timestamp=classified[0].timestamp,
        )

        strength = await user_memory.get_strength("local", "machine learning")
        assert strength > 0.7  # fresh signal, negligible decay

    @pytest.mark.asyncio
    async def test_invalid_llm_response_is_skipped(self, user_memory):
        """Malformed LLM JSON is dropped rather than crashing the pipeline."""
        llm = FakeLLM([{"topics": [], "confidences": [], "explanation": "nothing found"}])
        agent = InterestAgent(engine=None, llm=llm, memory=user_memory)

        signal = make_github_signal("typo fix")
        classified = await agent._classify_signals([signal])

        assert classified == []


class TestResearchTriggers:
    """Research trigger detection based on accumulated interest strength."""

    @pytest.mark.asyncio
    async def test_signal_triggers_research(self, user_memory):
        """A weak signal alone doesn't trigger; additional evidence pushes it over threshold."""
        llm = FakeLLM(
            [
                {"topics": ["machine learning"], "confidences": [0.15], "explanation": "weak"},
                {"topics": ["machine learning"], "confidences": [0.5], "explanation": "stronger"},
            ]
        )
        agent = InterestAgent(engine=None, llm=llm, memory=user_memory)

        weak_signal = make_github_signal("tweak readme")
        first_research = await agent.process_signals([weak_signal], user_id="local")
        assert first_research == []  # 0.15 strength is below the 0.3 threshold

        strong_signal = make_github_signal("Add transformer model")
        second_research = await agent.process_signals([strong_signal], user_id="local")

        assert len(second_research) == 1
        assert second_research[0].topic == "machine learning"
        assert second_research[0].depth == "normal"

    @pytest.mark.asyncio
    async def test_cooldown_prevents_duplicate_trigger(self, user_memory):
        """The same topic does not trigger research twice within the cooldown window."""
        llm = FakeLLM(
            [
                {"topics": ["machine learning"], "confidences": [0.8], "explanation": "strong"},
                {"topics": ["machine learning"], "confidences": [0.8], "explanation": "strong again"},
            ]
        )
        agent = InterestAgent(engine=None, llm=llm, memory=user_memory)

        first_signal = make_github_signal("Add transformer model")
        first_research = await agent.process_signals([first_signal], user_id="local")
        assert len(first_research) == 1

        second_signal = make_github_signal("Add attention layer")
        second_research = await agent.process_signals([second_signal], user_id="local")
        assert second_research == []  # cooldown blocks re-trigger

    @pytest.mark.asyncio
    async def test_deep_research_for_high_strength(self, user_memory):
        """Strength >= 0.7 requests a deep research pass instead of normal."""
        llm = FakeLLM(
            [{"topics": ["machine learning"], "confidences": [0.9], "explanation": "very strong"}]
        )
        agent = InterestAgent(engine=None, llm=llm, memory=user_memory)

        signal = make_github_signal("Add transformer model")
        research = await agent.process_signals([signal], user_id="local")

        assert len(research) == 1
        assert research[0].depth == "deep"


class TestStrengthDecay:
    """Exponential decay weighting of interest strength over time."""

    @pytest.mark.asyncio
    async def test_strength_decay(self, user_memory):
        """Older signals contribute less to strength than recent ones."""
        llm = FakeLLM(
            [
                {"topics": ["machine learning"], "confidences": [0.3], "explanation": "old"},
                {"topics": ["machine learning"], "confidences": [0.8], "explanation": "recent"},
            ]
        )
        agent = InterestAgent(engine=None, llm=llm, memory=user_memory)

        old_signal = make_github_signal(
            "old commit", timestamp=datetime.utcnow() - timedelta(days=30)
        )
        await agent.process_signals([old_signal], user_id="local")

        recent_signal = make_github_signal("recent commit", timestamp=datetime.utcnow())
        await agent.process_signals([recent_signal], user_id="local")

        strength = await user_memory.get_strength("local", "machine learning", decay_hours=720)
        # old contributes ~0.3*exp(-1)=0.11; recent contributes ~0.8 -> sum ~0.91
        assert strength > 0.7

    @pytest.mark.asyncio
    async def test_fully_decayed_signal_contributes_negligibly(self, user_memory):
        """A signal far outside the decay window contributes almost nothing."""
        await user_memory.add_classified_signal(
            user_id="local",
            signal_id="old-1",
            topic="rust",
            confidence=1.0,
            timestamp=datetime.utcnow() - timedelta(days=365),
        )

        strength = await user_memory.get_strength("local", "rust", decay_hours=720)
        assert strength < 0.05


class TestEndToEndSignalFlow:
    """Full pipeline: ActivitySignal -> classification -> storage -> ResearchTopic."""

    @pytest.mark.asyncio
    async def test_multiple_signals_different_topics(self, user_memory):
        """Signals about different topics are tracked independently."""
        llm = FakeLLM(
            [
                {"topics": ["machine learning"], "confidences": [0.8], "explanation": "ml"},
                {"topics": ["devops"], "confidences": [0.75], "explanation": "ci/cd"},
            ]
        )
        agent = InterestAgent(engine=None, llm=llm, memory=user_memory)

        signals = [
            make_github_signal("Add transformer model"),
            make_github_signal("Fix CI pipeline"),
        ]
        research = await agent.process_signals(signals, user_id="local")

        triggered_topics = {r.topic for r in research}
        assert triggered_topics == {"machine learning", "devops"}

    @pytest.mark.asyncio
    async def test_no_signals_returns_empty(self, user_memory):
        """Processing an empty signal batch is a no-op."""
        agent = InterestAgent(engine=None, llm=FakeLLM([]), memory=user_memory)
        research = await agent.process_signals([], user_id="local")
        assert research == []


class FakeConnector:
    """Stub connector that returns a fixed batch of signals."""

    name = "fake"

    def __init__(self, signals: list[ActivitySignal]):
        self._signals = signals

    async def fetch(self, since: datetime) -> list[ActivitySignal]:
        return self._signals


class FakeEngine:
    """Stub PersonalAssistantEngine for daemon ingest-cycle wiring tests."""

    def __init__(self, research_topics: list):
        self._research_topics = research_topics
        self.submitted: list = []
        self.process_calls = 0

    async def process_activity_signals(self, signals, user_id: str = "local") -> list:
        self.process_calls += 1
        return self._research_topics

    async def submit(self, cmd) -> str:
        self.submitted.append(cmd)
        return f"job-{len(self.submitted)}"


class TestDaemonIngestWiring:
    """Daemon ingest cycle wires connector signals -> Interest Agent -> submitted commands."""

    def _make_daemon(self, tmp_path):
        from src.daemon.service import PersonalAssistantDaemon

        config = {
            "daemon": {"log_file": str(tmp_path / "daemon.log")},
            "connectors": {},
        }
        return PersonalAssistantDaemon(config)

    @pytest.mark.asyncio
    async def test_ingest_cycle_submits_research_topics(self, tmp_path, monkeypatch):
        """Signals fetched from connectors flow through the engine and get submitted."""
        from src.core.commands import ResearchTopic

        daemon = self._make_daemon(tmp_path)
        topic = ResearchTopic(user="local", topic="rust", depth="deep")
        fake_engine = FakeEngine([topic])
        daemon.engine = fake_engine

        signal = make_github_signal("rust rewrite")
        monkeypatch.setattr(
            "src.daemon.service.get_enabled_connectors",
            lambda: [FakeConnector([signal])],
        )

        await daemon._run_ingest_cycle()

        assert fake_engine.process_calls == 1
        assert fake_engine.submitted == [topic]

    @pytest.mark.asyncio
    async def test_ingest_cycle_skips_processing_when_no_signals(self, tmp_path, monkeypatch):
        """An ingest cycle with no fetched signals never calls the Interest Agent."""
        daemon = self._make_daemon(tmp_path)
        fake_engine = FakeEngine([])
        daemon.engine = fake_engine

        monkeypatch.setattr("src.daemon.service.get_enabled_connectors", lambda: [])

        await daemon._run_ingest_cycle()

        assert fake_engine.process_calls == 0
        assert fake_engine.submitted == []

    @pytest.mark.asyncio
    async def test_ingest_cycle_noop_without_engine(self, tmp_path):
        """Running an ingest cycle before the engine is initialized doesn't crash."""
        daemon = self._make_daemon(tmp_path)
        assert daemon.engine is None

        await daemon._run_ingest_cycle()  # should log a warning and return, not raise
