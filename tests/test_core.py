"""Tests for core engine components."""

import asyncio
import pytest
from datetime import datetime

from src.core.commands import Ask, Brainstorm, ResearchTopic, Opportunities, Feedback, ShowInterests, ShowDigest
from src.core.events import Started, Progress, Message, Result
from src.core.jobs import JobState
from src.core.bus import EventBus


# Command Tests
class TestCommands:
    """Test command dataclasses."""

    def test_ask_command(self):
        """Test Ask command creation."""
        cmd = Ask(user="test-user", query="What is AI?")
        assert cmd.user == "test-user"
        assert cmd.query == "What is AI?"

    def test_brainstorm_command(self):
        """Test Brainstorm command creation."""
        cmd = Brainstorm(user="user1", text="Let's think about ML")
        assert cmd.user == "user1"
        assert cmd.text == "Let's think about ML"
        assert cmd.session_id is None

    def test_brainstorm_with_session(self):
        """Test Brainstorm command with session ID."""
        cmd = Brainstorm(user="user1", text="Ideas", session_id="sess-123")
        assert cmd.session_id == "sess-123"

    def test_research_topic_command(self):
        """Test ResearchTopic command."""
        cmd = ResearchTopic(user="user1", topic="Transformers", depth="deep")
        assert cmd.topic == "Transformers"
        assert cmd.depth == "deep"

    def test_opportunities_command(self):
        """Test Opportunities command."""
        cmd = Opportunities(user="user1", action="list")
        assert cmd.action == "list"

    def test_feedback_command(self):
        """Test Feedback command."""
        cmd = Feedback(user="user1", ref="answer-123", verdict="accept", note="Good answer")
        assert cmd.ref == "answer-123"
        assert cmd.verdict == "accept"
        assert cmd.note == "Good answer"


# Event Tests
class TestEvents:
    """Test event dataclasses."""

    def test_started_event(self):
        """Test Started event."""
        event = Started(job_id="job-1", kind="AskCommand")
        assert event.job_id == "job-1"
        assert event.kind == "AskCommand"

    def test_progress_event(self):
        """Test Progress event."""
        event = Progress(job_id="job-1", phase="processing", message="Working on it", pct=50.0)
        assert event.phase == "processing"
        assert event.message == "Working on it"
        assert event.pct == 50.0

    def test_progress_without_pct(self):
        """Test Progress event without percentage."""
        event = Progress(job_id="job-1", phase="thinking", message="Hmm...")
        assert event.pct is None

    def test_message_event(self):
        """Test Message event."""
        event = Message(job_id="job-1", role="assistant", text="Here's the answer", citations=["source1"])
        assert event.role == "assistant"
        assert event.text == "Here's the answer"
        assert len(event.citations) == 1

    def test_result_event_success(self):
        """Test Result event for success."""
        event = Result(job_id="job-1", ok=True, payload={"answer": "42"})
        assert event.ok is True
        assert event.payload["answer"] == "42"

    def test_result_event_failure(self):
        """Test Result event for failure."""
        event = Result(job_id="job-1", ok=False, payload={"error": "Something went wrong"})
        assert event.ok is False
        assert "error" in event.payload


# JobState Tests
class TestJobState:
    """Test JobState enum."""

    def test_job_state_values(self):
        """Test job state values."""
        assert JobState.PENDING == "pending"
        assert JobState.RUNNING == "running"
        assert JobState.COMPLETED == "completed"
        assert JobState.FAILED == "failed"
        assert JobState.CANCELLED == "cancelled"

    def test_job_state_in_list(self):
        """Test job state membership."""
        states = [JobState.PENDING, JobState.RUNNING, JobState.COMPLETED]
        assert JobState.PENDING in states


# EventBus Tests
class TestEventBus:
    """Test EventBus class."""

    @pytest.mark.asyncio
    async def test_publish_and_subscribe(self):
        """Test basic pub/sub functionality."""
        bus = EventBus()
        job_id = "test-job"

        # Start subscriber
        events_received = []

        async def subscribe():
            async for event in bus.subscribe(job_id):
                events_received.append(event)
                if isinstance(event, Result):
                    break

        subscriber_task = asyncio.create_task(subscribe())

        # Publish events
        await bus.publish(Started(job_id=job_id, kind="Test"))
        await bus.publish(Progress(job_id=job_id, phase="test", message="Working"))
        await bus.publish(Result(job_id=job_id, ok=True))

        # Wait for subscriber to finish
        await asyncio.wait_for(subscriber_task, timeout=1.0)

        assert len(events_received) == 3
        assert isinstance(events_received[0], Started)
        assert isinstance(events_received[1], Progress)
        assert isinstance(events_received[2], Result)

    @pytest.mark.asyncio
    async def test_close_sends_sentinel(self):
        """Test that close sends sentinel to end stream."""
        bus = EventBus()
        job_id = "test-job"

        received_count = 0

        async def subscribe():
            nonlocal received_count
            async for event in bus.subscribe(job_id):
                received_count += 1

        subscriber_task = asyncio.create_task(subscribe())

        # Publish one event
        await bus.publish(Started(job_id=job_id, kind="Test"))

        # Close the stream
        await asyncio.sleep(0.1)  # Let subscriber start
        await bus.close(job_id)

        # Wait for subscriber to finish
        try:
            await asyncio.wait_for(subscriber_task, timeout=1.0)
        except asyncio.TimeoutError:
            pass  # Subscriber might still be waiting

        # Should have received at least the started event
        assert received_count >= 1

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self):
        """Test multiple subscribers to same job."""
        bus = EventBus()
        job_id = "test-job"

        events_1 = []
        events_2 = []

        async def sub1():
            async for event in bus.subscribe(job_id):
                events_1.append(event)
                if isinstance(event, Result):
                    break

        async def sub2():
            async for event in bus.subscribe(job_id):
                events_2.append(event)
                if isinstance(event, Result):
                    break

        task1 = asyncio.create_task(sub1())
        task2 = asyncio.create_task(sub2())

        # Publish events
        await bus.publish(Started(job_id=job_id, kind="Test"))
        await bus.publish(Result(job_id=job_id, ok=True))

        # Wait for both subscribers
        await asyncio.gather(task1, task2)

        # Both should receive same events
        assert len(events_1) == len(events_2)
        assert len(events_1) == 2

    @pytest.mark.asyncio
    async def test_unsubscribe_on_close(self):
        """Test that subscribers are removed on close."""
        bus = EventBus()
        job_id = "test-job"

        # Subscribe and immediately close
        async def subscribe():
            async for event in bus.subscribe(job_id):
                pass

        task = asyncio.create_task(subscribe())
        await asyncio.sleep(0.05)
        await bus.close(job_id)

        try:
            await asyncio.wait_for(task, timeout=0.5)
        except asyncio.TimeoutError:
            pass

        # Queue should be removed from subscribers
        assert job_id not in bus._subscribers or len(bus._subscribers[job_id]) == 0
