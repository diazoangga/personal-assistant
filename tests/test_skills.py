"""Tests for skills library."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.skills.topic_extraction import extract_topics
from src.skills.classification import classify_intent, classify_activity, IntentClassification, ActivityClassification
from src.skills.retrieval import retrieve_knowledge, format_retrieval_context
from src.skills.summarization import summarize_with_citations, summarize_activity
from src.store.vector import KnowledgeBase, Chunk, Hit


# Mock fixtures
@pytest.fixture
def mock_llm():
    """Create a mock LLM runtime."""
    llm = AsyncMock()
    llm.chat = AsyncMock()
    llm.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    return llm


@pytest.fixture
def mock_kb():
    """Create a mock KnowledgeBase."""
    kb = MagicMock(spec=KnowledgeBase)
    kb.search = AsyncMock()
    return kb


# Topic Extraction Tests
class TestTopicExtraction:
    """Test topic extraction skill."""

    @pytest.mark.asyncio
    async def test_extract_topics_basic(self, mock_llm):
        """Test basic topic extraction."""
        mock_response = MagicMock()
        mock_response.content = '["machine learning", "python", "AI"]'
        mock_llm.chat.return_value = mock_response

        topics = await extract_topics("This text is about machine learning and Python AI", mock_llm)

        assert len(topics) > 0
        assert isinstance(topics, list)
        mock_llm.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_extract_topics_max_topics(self, mock_llm):
        """Test max topics limit."""
        mock_response = MagicMock()
        mock_response.content = '["topic1", "topic2", "topic3", "topic4", "topic5", "topic6"]'
        mock_llm.chat.return_value = mock_response

        topics = await extract_topics("Test text", mock_llm, max_topics=3)

        assert len(topics) <= 3

    @pytest.mark.asyncio
    async def test_extract_topics_json_parse_error(self, mock_llm):
        """Test fallback when JSON parsing fails."""
        mock_response = MagicMock()
        mock_response.content = "topic1\ntopic2\ntopic3"  # Not valid JSON
        mock_llm.chat.return_value = mock_response

        topics = await extract_topics("Test text", mock_llm)

        assert len(topics) > 0  # Should fallback to split by newlines

    @pytest.mark.asyncio
    async def test_extract_topics_empty_response(self, mock_llm):
        """Test handling empty response."""
        mock_response = MagicMock()
        mock_response.content = ""
        mock_llm.chat.return_value = mock_response

        topics = await extract_topics("Test", mock_llm)

        assert topics == []


# Classification Tests
class TestClassification:
    """Test classification skills."""

    @pytest.mark.asyncio
    async def test_classify_intent_ask(self, mock_llm):
        """Test classifying ask intent."""
        mock_response = MagicMock()
        mock_response.content = '{"intent": "ask", "confidence": 0.9, "topics": ["python"], "urgency": "medium"}'
        mock_llm.chat.return_value = mock_response

        result = await classify_intent("How do I use Python?", mock_llm)

        assert isinstance(result, IntentClassification)
        assert result.intent == "ask"
        assert result.confidence == 0.9

    @pytest.mark.asyncio
    async def test_classify_intent_brainstorm(self, mock_llm):
        """Test classifying brainstorm intent."""
        mock_response = MagicMock()
        mock_response.content = '{"intent": "brainstorm", "confidence": 0.85, "topics": ["ideas"], "urgency": "low"}'
        mock_llm.chat.return_value = mock_response

        result = await classify_intent("Let me think through some ideas", mock_llm)

        assert result.intent == "brainstorm"

    @pytest.mark.asyncio
    async def test_classify_intent_fallback(self, mock_llm):
        """Test fallback on JSON parse error."""
        mock_response = MagicMock()
        mock_response.content = "invalid json"
        mock_llm.chat.return_value = mock_response

        result = await classify_intent("Test", mock_llm)

        assert result.intent == "ask"  # Default
        assert result.confidence == 0.3

    @pytest.mark.asyncio
    async def test_classify_activity_coding(self, mock_llm):
        """Test classifying coding activity."""
        mock_response = MagicMock()
        mock_response.content = '{"category": "coding", "topics": ["python", "api"], "learning_signal": true, "achievement_signal": true}'
        mock_llm.chat.return_value = mock_response

        result = await classify_activity("Implemented new API endpoint in Python", mock_llm)

        assert isinstance(result, ActivityClassification)
        assert result.category == "coding"

    @pytest.mark.asyncio
    async def test_classify_activity_fallback(self, mock_llm):
        """Test activity classification fallback."""
        mock_response = MagicMock()
        mock_response.content = "not json"
        mock_llm.chat.return_value = mock_response

        result = await classify_activity("Test", mock_llm)

        assert result.category == "other"
        assert not result.learning_signal


# Retrieval Tests
class TestRetrieval:
    """Test retrieval skill."""

    @pytest.mark.asyncio
    async def test_retrieve_knowledge_basic(self, mock_kb):
        """Test basic retrieval."""
        chunk = Chunk(
            id="test",
            text="Test content",
            embedding=[0.1],
            source_url="https://example.com",
            connector="arxiv",
            topic="ml",
            ingested_at="2024-01-01T00:00:00Z",
            quality=0.8,
        )
        hit = Hit(chunk=chunk, score=0.9)
        mock_kb.search.return_value = [hit] * 10

        hits = await retrieve_knowledge("query", mock_kb, k=5)

        assert len(hits) <= 5
        mock_kb.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_retrieve_knowledge_topic_filter(self, mock_kb):
        """Test retrieval with topic filter."""
        chunk1 = Chunk(id="1", text="T1", embedding=[0.1], source_url=None, connector="arxiv", topic="ml", ingested_at="2024-01-01T00:00:00Z", quality=0.8)
        chunk2 = Chunk(id="2", text="T2", embedding=[0.1], source_url=None, connector="arxiv", topic="nlp", ingested_at="2024-01-01T00:00:00Z", quality=0.8)
        hits = [Hit(chunk=chunk1, score=0.9), Hit(chunk=chunk2, score=0.85)]
        mock_kb.search.return_value = hits

        filtered = await retrieve_knowledge("query", mock_kb, topic_filter="ml")

        assert len(filtered) == 1
        assert filtered[0].chunk.topic == "ml"

    def test_format_retrieval_context_empty(self):
        """Test formatting empty retrieval context."""
        context = format_retrieval_context([])
        assert "No relevant information" in context

    def test_format_retrieval_context_with_hits(self):
        """Test formatting retrieval hits."""
        chunk = Chunk(
            id="test",
            text="Important content here",
            embedding=[0.1],
            source_url="https://example.com",
            connector="arxiv",
            topic="ml",
            ingested_at="2024-01-01T00:00:00Z",
            quality=0.8,
        )
        hit = Hit(chunk=chunk, score=0.95)

        context = format_retrieval_context([hit])

        assert "Important content here" in context
        assert "https://example.com" in context
        assert "0.95" in context

    def test_format_retrieval_context_max_tokens(self):
        """Test max tokens limit in formatting."""
        chunks = []
        for i in range(10):
            chunk = Chunk(
                id=f"chunk-{i}",
                text="Word " * 100,  # Long text
                embedding=[0.1],
                source_url=None,
                connector="arxiv",
                topic="ml",
                ingested_at="2024-01-01T00:00:00Z",
                quality=0.8,
            )
            chunks.append(Hit(chunk=chunk, score=0.9))

        context = format_retrieval_context(chunks, max_tokens=500)

        # Should truncate to respect max_tokens
        assert len(context) // 4 <= 600  # Rough estimate


# Summarization Tests
class TestSummarization:
    """Test summarization skills."""

    @pytest.mark.asyncio
    async def test_summarize_with_citations_basic(self, mock_llm):
        """Test basic summarization with citations."""
        chunk = Chunk(
            id="test",
            text="Key finding: AI improves productivity by 40%",
            embedding=[0.1],
            source_url="https://example.com/study",
            connector="arxiv",
            topic="ai",
            ingested_at="2024-01-01T00:00:00Z",
            quality=0.9,
        )
        hit = Hit(chunk=chunk, score=0.95)

        mock_response = MagicMock()
        mock_response.content = "AI improves productivity [1]."
        mock_llm.chat.return_value = mock_response

        summary = await summarize_with_citations(
            "What does AI do?",
            [hit],
            mock_llm,
            max_length="short",
        )

        assert isinstance(summary, str)
        mock_llm.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_summarize_with_citations_no_hits(self, mock_llm):
        """Test summarization with no hits."""
        summary = await summarize_with_citations("Query", [], mock_llm)
        assert "No relevant information" in summary
        mock_llm.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_summarize_activity_basic(self, mock_llm):
        """Test activity summarization."""
        mock_response = MagicMock()
        mock_response.content = "- Implemented feature\n- Topics: python, api\n- Learning: new framework"
        mock_llm.chat.return_value = mock_response

        summary = await summarize_activity(
            "Built new API endpoint using FastAPI with authentication",
            mock_llm,
            include_learnings=True,
        )

        assert isinstance(summary, str)
        mock_llm.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_summarize_activity_without_learnings(self, mock_llm):
        """Test activity summary without learnings."""
        mock_response = MagicMock()
        mock_response.content = "- Summary here"
        mock_llm.chat.return_value = mock_response

        summary = await summarize_activity("Activity", mock_llm, include_learnings=False)

        assert isinstance(summary, str)
        # Check that prompt didn't include learnings section
        call_args = mock_llm.chat.call_args
        prompt = call_args[1]["messages"][0]["content"]
        assert "Key learnings" not in prompt or "learnings" not in prompt.lower()
