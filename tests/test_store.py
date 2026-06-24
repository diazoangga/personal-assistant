"""Tests for storage layer - vector, memory, and graph stores."""

import asyncio
import hashlib
import os
import tempfile
from datetime import datetime, timedelta

import pytest

from src.store.vector import KnowledgeBase, Chunk, Hit, semantic_chunks
from src.store.memory import UserMemory, InterestNode, InterestEdge, Opportunity, Feedback, Proposal


# Fixtures
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


# Vector Store Tests
class TestChunk:
    """Test Chunk dataclass."""

    def test_chunk_creation(self):
        """Test creating a chunk."""
        chunk = Chunk(
            id="test-id",
            text="Test content",
            embedding=[0.1, 0.2, 0.3],
            source_url="https://example.com",
            connector="github_research",
            topic="machine-learning",
            ingested_at="2024-01-01T00:00:00Z",
            quality=0.85,
        )
        assert chunk.id == "test-id"
        assert chunk.text == "Test content"
        assert len(chunk.embedding) == 3
        assert chunk.quality == 0.85

    def test_chunk_to_dict(self):
        """Test converting chunk to dictionary."""
        chunk = Chunk(
            id="test-id",
            text="Test",
            embedding=[0.1],
            source_url=None,
            connector="arxiv",
            topic="ai",
            ingested_at="2024-01-01T00:00:00Z",
            quality=0.9,
        )
        data = chunk.to_dict()
        assert data["id"] == "test-id"
        assert data["text"] == "Test"
        assert data["connector"] == "arxiv"
        assert "embedding" not in data  # Embedding not in dict

    def test_chunk_from_dict(self):
        """Test creating chunk from dictionary."""
        data = {
            "id": "test-id",
            "text": "Test",
            "connector": "github_research",
            "topic": "python",
            "ingested_at": "2024-01-01T00:00:00Z",
            "quality": 0.75,
        }
        embedding = [0.5, 0.6]
        chunk = Chunk.from_dict(data, embedding)
        assert chunk.id == "test-id"
        assert chunk.embedding == embedding
        assert chunk.quality == 0.75


class TestHit:
    """Test Hit dataclass."""

    def test_hit_creation(self):
        """Test creating a hit."""
        chunk = Chunk(
            id="test",
            text="Test",
            embedding=[0.1],
            source_url=None,
            connector="arxiv",
            topic="ai",
            ingested_at="2024-01-01T00:00:00Z",
            quality=0.8,
        )
        hit = Hit(chunk=chunk, score=0.95)
        assert hit.score == 0.95
        assert hit.chunk.id == "test"


class TestKnowledgeBaseComputeId:
    """Test KnowledgeBase static methods."""

    def test_compute_id_consistency(self):
        """Test that same text produces same ID."""
        text = "Test content for hashing"
        id1 = KnowledgeBase.compute_id(text)
        id2 = KnowledgeBase.compute_id(text)
        assert id1 == id2

    def test_compute_id_different_texts(self):
        """Test that different texts produce different IDs."""
        id1 = KnowledgeBase.compute_id("Text 1")
        id2 = KnowledgeBase.compute_id("Text 2")
        assert id1 != id2

    def test_compute_id_case_insensitive(self):
        """Test that ID computation is case insensitive."""
        id1 = KnowledgeBase.compute_id("Test Text")
        id2 = KnowledgeBase.compute_id("test text")
        assert id1 == id2

    def test_compute_id_length(self):
        """Test that ID is 32 characters."""
        id = KnowledgeBase.compute_id("Test")
        assert len(id) == 32


class TestSemanticChunks:
    """Test semantic chunking function."""

    def test_single_paragraph(self):
        """Test chunking single paragraph."""
        text = "This is a test paragraph. It has multiple sentences. Here is another one."
        chunks = semantic_chunks(text)
        assert len(chunks) > 0
        assert all(isinstance(c, str) for c in chunks)

    def test_multiple_paragraphs(self):
        """Test chunking multiple paragraphs."""
        text = "First paragraph here.\n\nSecond paragraph there.\n\nThird one too."
        chunks = semantic_chunks(text)
        assert len(chunks) >= 3

    def test_empty_text(self):
        """Test chunking empty text."""
        chunks = semantic_chunks("")
        assert len(chunks) == 0

    def test_max_tokens(self):
        """Test max token limit."""
        text = " ".join(["word"] * 1000)
        chunks = semantic_chunks(text, max_tokens=100)
        assert len(chunks) > 1


# Memory Store Tests
class TestUserMemory:
    """Test UserMemory class."""

    @pytest.mark.asyncio
    async def test_initialize_creates_tables(self, user_memory):
        """Test that initialize creates all tables."""
        # Should not raise any errors
        assert user_memory._db is not None

    @pytest.mark.asyncio
    async def test_set_and_get_profile(self, user_memory):
        """Test setting and getting profile values."""
        await user_memory.set_profile("name", "Test User")
        name = await user_memory.get_profile("name")
        assert name == "Test User"

    @pytest.mark.asyncio
    async def test_update_profile(self, user_memory):
        """Test updating profile value."""
        await user_memory.set_profile("theme", "dark")
        await user_memory.set_profile("theme", "light")
        theme = await user_memory.get_profile("theme")
        assert theme == "light"

    @pytest.mark.asyncio
    async def test_get_nonexistent_profile(self, user_memory):
        """Test getting nonexistent profile key."""
        value = await user_memory.get_profile("nonexistent")
        assert value is None

    @pytest.mark.asyncio
    async def test_get_all_profile(self, user_memory):
        """Test getting all profile values."""
        await user_memory.set_profile("key1", "value1")
        await user_memory.set_profile("key2", {"nested": "value"})
        profile = await user_memory.get_all_profile()
        assert "key1" in profile
        assert "key2" in profile
        assert profile["key1"] == "value1"

    @pytest.mark.asyncio
    async def test_upsert_interest(self, user_memory):
        """Test upserting interest nodes."""
        node = InterestNode(
            id="ml",
            label="Machine Learning",
            strength=0.8,
            last_active=datetime.utcnow().isoformat(),
            decay_rate=0.01,
        )
        await user_memory.upsert_interest(node)
        interests = await user_memory.get_interests()
        assert len(interests) == 1
        assert interests[0].label == "Machine Learning"

    @pytest.mark.asyncio
    async def test_add_interest_edge(self, user_memory):
        """Test adding interest edges."""
        # Add nodes first
        node1 = InterestNode(id="ai", label="AI", strength=0.9, last_active=datetime.utcnow().isoformat())
        node2 = InterestNode(id="ml", label="ML", strength=0.8, last_active=datetime.utcnow().isoformat())
        await user_memory.upsert_interest(node1)
        await user_memory.upsert_interest(node2)

        # Add edge
        edge = InterestEdge(source_id="ai", target_id="ml", weight=0.7, relation_type="parent_of")
        await user_memory.add_interest_edge(edge)

        # Get related interests
        related = await user_memory.get_related_interests("ai")
        assert len(related) == 1
        assert related[0].id == "ml"

    @pytest.mark.asyncio
    async def test_decay_interests(self, user_memory):
        """Test interest decay."""
        old_date = (datetime.utcnow() - timedelta(days=10)).isoformat()
        node = InterestNode(id="old", label="Old Topic", strength=0.5, last_active=old_date, decay_rate=0.01)
        await user_memory.upsert_interest(node)

        await user_memory.decay_interests(days=10)

        interests = await user_memory.get_interests()
        assert len(interests) == 1
        assert interests[0].strength < 0.5  # Should have decayed

    @pytest.mark.asyncio
    async def test_add_opportunity(self, user_memory):
        """Test adding opportunities."""
        opp = Opportunity(
            id="opp-1",
            title="ML Engineer Position",
            description="Great opportunity",
            source_url="https://example.com/job",
            relevance_score=0.85,
            matched_interests=["ml", "ai"],
            created_at=datetime.utcnow().isoformat(),
        )
        await user_memory.add_opportunity(opp)

        opportunities = await user_memory.get_opportunities()
        assert len(opportunities) == 1
        assert opportunities[0].title == "ML Engineer Position"

    @pytest.mark.asyncio
    async def test_update_opportunity_status(self, user_memory):
        """Test updating opportunity status."""
        opp = Opportunity(
            id="opp-1",
            title="Job",
            description="Desc",
            source_url=None,
            relevance_score=0.8,
            matched_interests=[],
            created_at=datetime.utcnow().isoformat(),
            status="new",
        )
        await user_memory.add_opportunity(opp)
        await user_memory.update_opportunity_status("opp-1", "saved")

        opps = await user_memory.get_opportunities(status="saved")
        assert len(opps) == 1
        assert opps[0].status == "saved"

    @pytest.mark.asyncio
    async def test_add_feedback(self, user_memory):
        """Test adding feedback."""
        feedback = Feedback(
            id="fb-1",
            job_id="job-123",
            feedback_type="thumbs_up",
            comment="Great answer!",
            created_at=datetime.utcnow().isoformat(),
        )
        await user_memory.add_feedback(feedback)

        retrieved = await user_memory.get_feedback("job-123")
        assert retrieved is not None
        assert retrieved.feedback_type == "thumbs_up"

    @pytest.mark.asyncio
    async def test_create_and_update_job(self, user_memory):
        """Test job lifecycle."""
        await user_memory.create_job("job-1", "AskCommand", {"query": "test"})
        job = await user_memory.get_job("job-1")
        assert job is not None
        assert job["command_type"] == "AskCommand"
        assert job["status"] == "pending"

        await user_memory.update_job_status("job-1", "completed")
        job = await user_memory.get_job("job-1")
        assert job["status"] == "completed"

    @pytest.mark.asyncio
    async def test_add_proposal(self, user_memory):
        """Test adding self-modification proposal."""
        proposal = Proposal(
            id="prop-1",
            proposal_type="new_skill",
            description="Add ranking skill",
            rationale="Needed for better results",
            code_diff=None,
        )
        await user_memory.add_proposal(proposal)

        proposals = await user_memory.get_pending_proposals()
        assert len(proposals) == 1
        assert proposals[0].description == "Add ranking skill"

    @pytest.mark.asyncio
    async def test_update_proposal_status(self, user_memory):
        """Test updating proposal status."""
        proposal = Proposal(
            id="prop-1",
            proposal_type="new_topic",
            description="Add NLP topic",
            rationale="User interested",
            code_diff=None,
        )
        await user_memory.add_proposal(proposal)
        await user_memory.update_proposal_status("prop-1", "approved")

        proposals = await user_memory.get_pending_proposals()
        assert len(proposals) == 0  # No longer pending
