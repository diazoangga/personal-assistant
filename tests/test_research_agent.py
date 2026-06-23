"""Tests for the Research Agent (R4).

End-to-end pipeline: search → expand → enrich → extract → link → persist → summarize.
Uses FakeLLM (deterministic responses) and replayed connectors (no live network).
"""

import json
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents.research.agent import ResearchAgent
from src.agents.research.tools.base import RawPaper
from src.store.knowledge import UnifiedKnowledgeStore


@pytest.fixture
async def temp_store():
    """Temporary knowledge store for tests."""
    _, db_path = tempfile.mkstemp(suffix=".db")
    store = UnifiedKnowledgeStore(db_path)
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
def fake_llm():
    """FakeLLM that cycles through predetermined responses."""

    class FakeLLM:
        def __init__(self):
            self.responses = []
            self.response_index = 0

        async def chat(self, messages, model_role=None):
            if self.response_index >= len(self.responses):
                return AsyncMock(content="{}")
            response_text = self.responses[self.response_index]
            self.response_index += 1
            return AsyncMock(content=response_text)

        def reset(self):
            self.response_index = 0

    return FakeLLM()


def make_raw_paper(title: str, arxiv_id: str = None, s2_id: str = None) -> RawPaper:
    """Helper to create test RawPaper objects."""
    return RawPaper(
        title=title,
        abstract="A detailed abstract of the paper.",
        authors=["Author A", "Author B"],
        published_date="2024-01-15",
        venue="Conference",
        year=2024,
        citation_count=10,
        reference_count=5,
        url="https://example.com",
        arxiv_id=arxiv_id,
        semantic_scholar_id=s2_id,
        source="test",
    )


class TestResearchAgent:
    @pytest.mark.asyncio
    async def test_research_basic_execution(self, temp_store, fake_llm):
        """Test basic research execution with mocked connectors."""
        # Prepare LLM responses for synthesis, entity extraction, relation extraction, summary
        fake_llm.responses = [
            # paper_synthesis for paper1
            json.dumps({
                "conclusion": "This paper presents a novel approach.",
                "notes": {
                    "key_contributions": ["Novel method"],
                    "methods": ["Attention mechanism"],
                    "limitations": ["Computational cost"],
                },
            }),
            # entity_extraction for paper1
            json.dumps([
                {"name": "Transformer", "category": "model", "description": "Architecture", "confidence": 0.95},
                {"name": "attention", "category": "concept", "description": "Mechanism", "confidence": 0.9},
            ]),
            # relation_extraction for paper1
            json.dumps([
                {"source": "Transformer", "target": "attention", "relation_type": "part_of", "weight": 0.95, "evidence": "Core component"},
            ]),
            # entity_extraction (again for linking)
            json.dumps([
                {"name": "Transformer", "category": "model", "description": "Architecture", "confidence": 0.95},
                {"name": "attention", "category": "concept", "description": "Mechanism", "confidence": 0.9},
            ]),
            # summarization
            "This research discovered that transformers rely on attention mechanisms.",
        ]

        # Create agent with mocked connectors
        agent = ResearchAgent(fake_llm, temp_store, {})

        # Mock Semantic Scholar connector
        paper1 = make_raw_paper("Attention Is All You Need", s2_id="abc123")

        async def mock_search(topic, limit):
            if "transformer" in topic.lower():
                return [paper1]
            return []

        agent.semantic_scholar.search = AsyncMock(side_effect=mock_search)
        agent.arxiv.search = AsyncMock(side_effect=mock_search)

        # Run research
        result = await agent.research("transformers", depth="shallow")

        assert result.topic == "transformers"
        assert result.new_papers >= 1
        assert result.new_concepts >= 1
        assert len(result.summary) > 0

        # Verify persistence: query store
        papers = await temp_store.find_citations_by_title("Attention Is All You Need")
        assert len(papers) >= 1

    @pytest.mark.asyncio
    async def test_research_with_interest_id_linking(self, temp_store, fake_llm):
        """Test that research links papers and concepts to interest."""
        fake_llm.responses = [
            json.dumps({"conclusion": "Conclusion", "notes": {"key_contributions": [], "methods": [], "limitations": []}}),
            json.dumps([{"name": "Concept1", "category": "concept", "description": "D", "confidence": 0.8}]),
            json.dumps([]),
            json.dumps([{"name": "Concept1", "category": "concept", "description": "D", "confidence": 0.8}]),
            "Summary.",
        ]

        # Create interest first
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        interest_id = "test-interest-1"
        await temp_store.upsert_interest({
            "id": interest_id,
            "label": "machine learning",
            "strength": 0.8,
            "created_at": now,
            "updated_at": now,
            "last_active": now,
        })

        agent = ResearchAgent(fake_llm, temp_store, {})
        paper1 = make_raw_paper("Paper", s2_id="p1")
        agent.semantic_scholar.search = AsyncMock(return_value=[paper1])
        agent.arxiv.search = AsyncMock(return_value=[])

        # Research linked to interest
        result = await agent.research("ml", interest_id=interest_id, depth="shallow")

        # Verify interest links exist
        citations = await temp_store.get_citations_for_interest(interest_id)
        assert len(citations) >= 1

    @pytest.mark.asyncio
    async def test_research_rerun_updates_not_duplicates(self, temp_store, fake_llm):
        """Running research twice on same topic should not duplicate papers, only update weights."""
        fake_llm.responses = [
            # First run: paper synthesis
            json.dumps({"conclusion": "C1", "notes": {"key_contributions": [], "methods": [], "limitations": []}}),
            json.dumps([{"name": "Concept1", "category": "concept", "description": "D", "confidence": 0.8}]),
            json.dumps([]),
            json.dumps([{"name": "Concept1", "category": "concept", "description": "D", "confidence": 0.8}]),
            "Summary 1.",
            # Second run: same responses (deterministic)
            json.dumps({"conclusion": "C1", "notes": {"key_contributions": [], "methods": [], "limitations": []}}),
            json.dumps([{"name": "Concept1", "category": "concept", "description": "D", "confidence": 0.8}]),
            json.dumps([]),
            json.dumps([{"name": "Concept1", "category": "concept", "description": "D", "confidence": 0.8}]),
            "Summary 2.",
        ]

        agent = ResearchAgent(fake_llm, temp_store, {})
        paper1 = make_raw_paper("Paper", s2_id="p1")
        agent.semantic_scholar.search = AsyncMock(return_value=[paper1])
        agent.arxiv.search = AsyncMock(return_value=[])

        # First research run
        result1 = await agent.research("topic1", depth="shallow")
        papers_after_1 = await temp_store.find_citations_by_title("Paper")
        count_1 = len(papers_after_1)

        # Second research run (same topic)
        result2 = await agent.research("topic1", depth="shallow")
        papers_after_2 = await temp_store.find_citations_by_title("Paper")
        count_2 = len(papers_after_2)

        # Paper should not be duplicated
        assert count_2 == count_1

    @pytest.mark.asyncio
    async def test_decision_depth_shallow_with_existing(self, temp_store, fake_llm):
        """Depth decision: lots of existing research → shallow."""
        agent = ResearchAgent(fake_llm, temp_store, {})

        # Many existing papers
        depth = agent._decide_depth("topic", existing_count=20, trigger_strength=0.5)
        assert depth == "shallow"

    @pytest.mark.asyncio
    async def test_decision_depth_deep_with_strong_interest(self, temp_store, fake_llm):
        """Depth decision: strong new interest + little existing → deep."""
        agent = ResearchAgent(fake_llm, temp_store, {})

        depth = agent._decide_depth("topic", existing_count=1, trigger_strength=0.85)
        assert depth == "deep"

    @pytest.mark.asyncio
    async def test_decision_depth_normal_default(self, temp_store, fake_llm):
        """Depth decision: moderate case → normal."""
        agent = ResearchAgent(fake_llm, temp_store, {})

        depth = agent._decide_depth("topic", existing_count=5, trigger_strength=0.6)
        assert depth == "normal"

    @pytest.mark.asyncio
    async def test_prioritize_sources_theory(self, temp_store, fake_llm):
        """Source prioritization: theory topics include arXiv."""
        agent = ResearchAgent(fake_llm, temp_store, {})

        sources = agent._prioritize_sources("neural network model architecture", depth="normal")
        assert "semantic_scholar" in sources
        assert "arxiv" in sources

    @pytest.mark.asyncio
    async def test_prioritize_sources_applied(self, temp_store, fake_llm):
        """Source prioritization: applied topics may skip arXiv."""
        agent = ResearchAgent(fake_llm, temp_store, {})

        sources = agent._prioritize_sources("web framework", depth="normal")
        assert "semantic_scholar" in sources

    @pytest.mark.asyncio
    async def test_prioritize_sources_shallow(self, temp_store, fake_llm):
        """Source prioritization: shallow depth limits sources."""
        agent = ResearchAgent(fake_llm, temp_store, {})

        sources = agent._prioritize_sources("machine learning", depth="shallow")
        assert len(sources) == 1
        assert sources[0] == "semantic_scholar"
