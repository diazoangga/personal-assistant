"""Tests for Research Agent skills (R3).

Entity/relation extraction, paper synthesis, summarization. All use FakeLLM
(injectable LLM mock) following the pattern in CLAUDE.md "Mocking LLMs".
"""

import json
from unittest.mock import AsyncMock

import pytest

from src.agents.research.skills.entity_extraction import extract_entities, ExtractedEntity
from src.agents.research.skills.relation_extraction import extract_relations, ExtractedRelation
from src.agents.research.skills.paper_synthesis import synthesize_paper, SynthesizedPaper
from src.agents.research.skills.summarization import summarize_run


@pytest.fixture
def fake_llm():
    """Fake LLM that returns predetermined responses."""

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

    return FakeLLM()


class TestEntityExtraction:
    @pytest.mark.asyncio
    async def test_extract_entities_basic(self, fake_llm):
        fake_llm.responses = [
            json.dumps([
                {"name": "Transformer", "category": "model", "description": "Attention-based", "confidence": 0.95},
                {"name": "BERT", "category": "model", "description": "Bidirectional", "confidence": 0.87},
                {"name": "attention", "category": "concept", "description": "Mechanism", "confidence": 0.92},
            ])
        ]

        result = await extract_entities("Paper about Transformers and attention...", fake_llm, "s2:abc123")

        assert len(result.entities) == 3
        assert result.entities[0].name == "Transformer"
        assert result.entities[0].category == "model"
        assert result.entities[0].confidence == 0.95
        assert result.source_id == "s2:abc123"

    @pytest.mark.asyncio
    async def test_confidence_filtering(self, fake_llm):
        fake_llm.responses = [
            json.dumps([
                {"name": "HighConf", "category": "concept", "description": "Good", "confidence": 0.8},
                {"name": "LowConf", "category": "concept", "description": "Bad", "confidence": 0.5},
                {"name": "Borderline", "category": "method", "description": "OK", "confidence": 0.6},
            ])
        ]

        result = await extract_entities(
            "Test", fake_llm, "s2:x", min_confidence=0.6
        )

        assert len(result.entities) == 2
        names = {e.name for e in result.entities}
        assert names == {"HighConf", "Borderline"}

    @pytest.mark.asyncio
    async def test_deduplication_by_name_and_category(self, fake_llm):
        fake_llm.responses = [
            json.dumps([
                {"name": "BERT", "category": "model", "description": "First mention", "confidence": 0.8},
                {"name": "BERT", "category": "model", "description": "Second mention", "confidence": 0.95},
                {"name": "bert", "category": "model", "description": "Case variant", "confidence": 0.7},
                {"name": "BERT", "category": "method", "description": "Different category", "confidence": 0.85},
            ])
        ]

        result = await extract_entities("Test", fake_llm, "s2:x")

        # Should have 2: one for BERT/model (highest conf=0.95) and one for BERT/method
        assert len(result.entities) == 2
        model_berts = [e for e in result.entities if e.category == "model"]
        assert len(model_berts) == 1
        assert model_berts[0].confidence == 0.95

    @pytest.mark.asyncio
    async def test_malformed_json_tolerance(self, fake_llm):
        fake_llm.responses = ['{"invalid": json}']
        result = await extract_entities("Test", fake_llm, "s2:x")
        assert result.entities == []

    @pytest.mark.asyncio
    async def test_markdown_code_block_stripping(self, fake_llm):
        fake_llm.responses = [
            f"""```json
{json.dumps([{"name": "Test", "category": "concept", "description": "D", "confidence": 0.9}])}
```"""
        ]

        result = await extract_entities("Test", fake_llm, "s2:x")
        assert len(result.entities) == 1
        assert result.entities[0].name == "Test"

    @pytest.mark.asyncio
    async def test_missing_optional_fields(self, fake_llm):
        fake_llm.responses = [
            json.dumps([
                {"name": "Entity", "category": "concept"},  # No description, confidence
                {"name": "Another", "category": "method", "confidence": 0.8},  # No description
            ])
        ]

        result = await extract_entities("Test", fake_llm, "s2:x", min_confidence=0.0)
        assert len(result.entities) == 2
        # Missing description should default to name
        assert result.entities[0].description == "Entity"
        # Missing confidence should default to 0 and be filtered
        assert all(e.confidence >= 0.0 for e in result.entities)


class TestRelationExtraction:
    @pytest.mark.asyncio
    async def test_extract_relations_basic(self, fake_llm):
        fake_llm.responses = [
            json.dumps([
                {"source": "BERT", "target": "Transformer", "relation_type": "extends", "weight": 0.95, "evidence": "BERT extends Transformer"},
                {"source": "attention", "target": "Transformer", "relation_type": "part_of", "weight": 0.9, "evidence": "Core component"},
            ])
        ]

        result = await extract_relations(
            ["BERT", "Transformer", "attention"], fake_llm, "s2:abc123"
        )

        assert len(result.relations) == 2
        assert result.relations[0].source == "BERT"
        assert result.relations[0].relation_type == "extends"
        assert result.source_id == "s2:abc123"

    @pytest.mark.asyncio
    async def test_closed_vocab_enforcement(self, fake_llm):
        fake_llm.responses = [
            json.dumps([
                {"source": "A", "target": "B", "relation_type": "uses", "weight": 0.8, "evidence": "E"},
                {"source": "B", "target": "C", "relation_type": "invents", "weight": 0.7, "evidence": "E"},  # Invalid type
                {"source": "A", "target": "C", "relation_type": "related_to", "weight": 0.6, "evidence": "E"},
            ])
        ]

        result = await extract_relations(["A", "B", "C"], fake_llm, "s2:x")

        # Only 2 should pass (uses and related_to), not invents
        assert len(result.relations) == 2
        assert all(r.relation_type in ["uses", "related_to"] for r in result.relations)

    @pytest.mark.asyncio
    async def test_concept_validation(self, fake_llm):
        fake_llm.responses = [
            json.dumps([
                {"source": "A", "target": "B", "relation_type": "uses", "weight": 0.8, "evidence": "E"},
                {"source": "A", "target": "Unknown", "relation_type": "uses", "weight": 0.7, "evidence": "E"},  # Unknown target
                {"source": "B", "target": "A", "relation_type": "competes_with", "weight": 0.6, "evidence": "E"},
            ])
        ]

        result = await extract_relations(["A", "B"], fake_llm, "s2:x")

        # Only 2 should pass (A→B uses, B→A competes_with), not A→Unknown
        assert len(result.relations) == 2

    @pytest.mark.asyncio
    async def test_deduplication_by_source_target_type(self, fake_llm):
        fake_llm.responses = [
            json.dumps([
                {"source": "A", "target": "B", "relation_type": "uses", "weight": 0.7, "evidence": "E1"},
                {"source": "A", "target": "B", "relation_type": "uses", "weight": 0.95, "evidence": "E2"},  # Higher weight
                {"source": "B", "target": "A", "relation_type": "uses", "weight": 0.8, "evidence": "E3"},  # Different direction
            ])
        ]

        result = await extract_relations(["A", "B"], fake_llm, "s2:x")

        # Should have 2: one A→B uses (weight 0.95), one B→A uses (weight 0.8)
        assert len(result.relations) == 2
        ab_uses = [r for r in result.relations if r.source == "A" and r.target == "B"]
        assert len(ab_uses) == 1
        assert ab_uses[0].weight == 0.95

    @pytest.mark.asyncio
    async def test_empty_concept_list(self, fake_llm):
        result = await extract_relations([], fake_llm, "s2:x")
        assert result.relations == []

    @pytest.mark.asyncio
    async def test_single_concept(self, fake_llm):
        result = await extract_relations(["A"], fake_llm, "s2:x")
        assert result.relations == []


class TestPaperSynthesis:
    @pytest.mark.asyncio
    async def test_synthesize_paper_basic(self, fake_llm):
        fake_llm.responses = [
            json.dumps({
                "conclusion": "This paper introduces a novel approach to neural networks.",
                "notes": {
                    "key_contributions": ["Novel architecture", "SOTA results"],
                    "methods": ["Attention mechanism", "Pretraining"],
                    "limitations": ["Computational cost", "Data requirements"],
                }
            })
        ]

        result = await synthesize_paper(
            "Attention Is All You Need",
            "We propose a new architecture...",
            "A novel transformer architecture",
            fake_llm,
            "s2:abc123",
        )

        assert isinstance(result, SynthesizedPaper)
        assert result.source_id == "s2:abc123"
        assert result.conclusion == "This paper introduces a novel approach to neural networks."
        assert "Novel architecture" in result.notes["key_contributions"]
        assert "Attention mechanism" in result.notes["methods"]

    @pytest.mark.asyncio
    async def test_synthesis_with_missing_fields(self, fake_llm):
        fake_llm.responses = [
            json.dumps({
                "conclusion": "Main contribution",
                # notes is missing, should be filled with defaults
            })
        ]

        result = await synthesize_paper("Title", "Abstract", None, fake_llm, "s2:x")

        assert result.conclusion == "Main contribution"
        assert result.notes == {"key_contributions": [], "methods": [], "limitations": []}

    @pytest.mark.asyncio
    async def test_synthesis_invalid_notes_structure(self, fake_llm):
        fake_llm.responses = [
            json.dumps({
                "conclusion": "Test",
                "notes": "not a dict",  # Should be dict
            })
        ]

        result = await synthesize_paper("Title", "Abstract", None, fake_llm, "s2:x")

        assert result.notes == {"key_contributions": [], "methods": [], "limitations": []}

    @pytest.mark.asyncio
    async def test_synthesis_malformed_json_fallback(self, fake_llm):
        fake_llm.responses = ["not valid json"]

        result = await synthesize_paper("Title", "Abstract", None, fake_llm, "s2:x")

        assert result.conclusion == ""
        assert result.notes == {"key_contributions": [], "methods": [], "limitations": []}

    @pytest.mark.asyncio
    async def test_synthesis_markdown_stripping(self, fake_llm):
        fake_llm.responses = [
            f"""```json
{json.dumps({"conclusion": "Result", "notes": {"key_contributions": ["A"], "methods": [], "limitations": []}})}
```"""
        ]

        result = await synthesize_paper("Title", "Abstract", None, fake_llm, "s2:x")

        assert result.conclusion == "Result"


class TestSummarization:
    @pytest.mark.asyncio
    async def test_summarize_run_with_papers(self, fake_llm):
        fake_llm.responses = [
            "Recent research on RAG discovered several key papers including Smith et al. (2024) on hybrid retrieval strategies and Johnson et al. (2023) on dense passage retrieval improvements."
        ]

        papers = [
            {"title": "Hybrid Retrieval Strategies", "authors": ["Smith"], "year": 2024},
            {"title": "Dense Passage Retrieval", "authors": ["Johnson"], "year": 2023},
        ]
        concepts = [{"name": "Retrieval"}, {"name": "Ranking"}]

        result = await summarize_run("retrieval augmented generation", papers, concepts, fake_llm)

        assert isinstance(result, str)
        assert len(result) > 0
        assert "RAG" in result or "retrieval" in result.lower()

    @pytest.mark.asyncio
    async def test_summarize_run_empty(self, fake_llm):
        result = await summarize_run("topic", [], [], fake_llm)
        assert result == ""

    @pytest.mark.asyncio
    async def test_summarize_run_length_cap(self, fake_llm):
        # Very long response should be capped
        long_response = "A" * 1000
        fake_llm.responses = [long_response]

        result = await summarize_run("topic", [{"title": "T", "authors": ["A"], "year": 2024}], [], fake_llm)

        assert len(result) <= 500

    @pytest.mark.asyncio
    async def test_summarize_run_with_json_authors(self, fake_llm):
        fake_llm.responses = [
            "The research revealed important findings on transformers from Vaswani et al. (2017)."
        ]

        papers = [
            {
                "title": "Attention Is All You Need",
                "authors": json.dumps(["Vaswani", "Shazeer"]),  # JSON-encoded
                "year": 2017,
            }
        ]

        result = await summarize_run("transformers", papers, [], fake_llm)

        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_summarize_run_markdown_stripping(self, fake_llm):
        fake_llm.responses = [
            """```
Summary paragraph here.
```"""
        ]

        papers = [{"title": "T", "authors": ["A"], "year": 2024}]
        result = await summarize_run("topic", papers, [], fake_llm)

        assert "```" not in result
        assert "Summary" in result
