"""Tests for the Research Agent's data-model additions to UnifiedKnowledgeStore:
citation graph (nodes + cites edges), interest<->citation linkage, and research_runs
provenance. See docs/research-agent.data-model.md.
"""

import os
import tempfile

import pytest

from src.store.knowledge import UnifiedKnowledgeStore, compute_citation_id


@pytest.fixture
def temp_db():
    """Create a temporary SQLite database file."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
async def store(temp_db):
    """Create a UnifiedKnowledgeStore instance with initialized (migrated) schema."""
    kb = UnifiedKnowledgeStore(temp_db)
    await kb.initialize()
    yield kb
    await kb.close()


def make_paper(**overrides) -> dict:
    paper = {
        "title": "Attention Is All You Need",
        "abstract": "We propose the Transformer...",
        "authors": '["Vaswani", "Shazeer"]',
        "published_date": "2017-06-12",
        "source": "arxiv",
        "arxiv_id": "1706.03762",
    }
    paper.update(overrides)
    return paper


class TestComputeCitationId:
    def test_priority_doi_over_arxiv(self):
        cid_doi = compute_citation_id({"doi": "10.1/abc", "arxiv_id": "1234.5678"})
        assert cid_doi.startswith("doi:")

    def test_priority_arxiv_over_s2(self):
        cid = compute_citation_id({"arxiv_id": "1234.5678", "semantic_scholar_id": "s2id"})
        assert cid.startswith("arxiv:")

    def test_falls_back_to_title_hash(self):
        cid = compute_citation_id({"title": "Some Paper"})
        assert cid.startswith("title:")

    def test_deterministic(self):
        a = compute_citation_id({"title": "Same Paper"})
        b = compute_citation_id({"title": "same paper"})  # case-insensitive
        assert a == b


class TestUpsertCitation:
    @pytest.mark.asyncio
    async def test_insert_then_fetch(self, store):
        citation_id = await store.upsert_citation(make_paper())
        row = await store.get_citation(citation_id)
        assert row is not None
        assert row["title"] == "Attention Is All You Need"
        assert row["arxiv_id"] == "1706.03762"

    @pytest.mark.asyncio
    async def test_reupsert_same_arxiv_id_updates_not_duplicates(self, store):
        id1 = await store.upsert_citation(make_paper())
        id2 = await store.upsert_citation(make_paper(citation_count=42))
        assert id1 == id2
        all_citations = await store.get_all_citations()
        assert len(all_citations) == 1
        row = await store.get_citation(id1)
        assert row["citation_count"] == 42

    @pytest.mark.asyncio
    async def test_cross_source_backfill_by_arxiv_id(self, store):
        """A paper first seen via arXiv (no doi) later seen via Semantic Scholar
        (same arxiv_id, now with a doi) should update the same row, not create a new one."""
        id1 = await store.upsert_citation(make_paper())
        id2 = await store.upsert_citation(
            make_paper(doi="10.1109/xyz", semantic_scholar_id="s2-123", source="semantic_scholar")
        )
        assert id1 == id2
        row = await store.get_citation(id1)
        assert row["doi"] == "10.1109/xyz"
        assert row["semantic_scholar_id"] == "s2-123"
        # abstract wasn't re-sent in the second call's overrides removal case, but here it was
        # carried via make_paper() defaults, so this just confirms no row was lost.
        all_citations = await store.get_all_citations()
        assert len(all_citations) == 1

    @pytest.mark.asyncio
    async def test_coalesce_preserves_existing_field_when_not_resent(self, store):
        id1 = await store.upsert_citation(make_paper(tldr="A short summary."))
        await store.upsert_citation(make_paper(citation_count=5))  # no tldr this time
        row = await store.get_citation(id1)
        assert row["tldr"] == "A short summary."
        assert row["citation_count"] == 5

    @pytest.mark.asyncio
    async def test_explicit_id_used_as_is(self, store):
        """Backward-compat path: callers like the Brainstorming Agent pass an explicit id."""
        citation_id = await store.upsert_citation(
            {"id": "explicit-id-123", "title": "Some Source", "abstract": "..."}
        )
        assert citation_id == "explicit-id-123"
        row = await store.get_citation("explicit-id-123")
        assert row is not None

    @pytest.mark.asyncio
    async def test_notes_round_trip_as_json(self, store):
        citation_id = await store.upsert_citation(
            make_paper(notes={"key_contributions": ["a", "b"]})
        )
        row = await store.get_citation(citation_id)
        assert "key_contributions" in row["notes"]


class TestCitationNotes:
    @pytest.mark.asyncio
    async def test_update_citation_notes(self, store):
        citation_id = await store.upsert_citation(make_paper())
        await store.update_citation_notes(
            citation_id, conclusion="A landmark paper.", notes={"limitations": ["compute cost"]}
        )
        row = await store.get_citation(citation_id)
        assert row["conclusion"] == "A landmark paper."
        assert "limitations" in row["notes"]

    @pytest.mark.asyncio
    async def test_update_citation_notes_partial_keeps_other_field(self, store):
        citation_id = await store.upsert_citation(make_paper())
        await store.update_citation_notes(citation_id, conclusion="First.")
        await store.update_citation_notes(citation_id, notes={"x": 1})
        row = await store.get_citation(citation_id)
        assert row["conclusion"] == "First."
        assert "x" in row["notes"]


class TestIsKnownCitation:
    @pytest.mark.asyncio
    async def test_known_and_unknown(self, store):
        citation_id = await store.upsert_citation(make_paper())
        assert await store.is_known_citation(citation_id) is True
        assert await store.is_known_citation("does-not-exist") is False


class TestCitationGraph:
    @pytest.mark.asyncio
    async def test_add_edge_then_get_edges_both_directions(self, store):
        a = await store.upsert_citation(make_paper(title="Paper A", arxiv_id="a"))
        b = await store.upsert_citation(make_paper(title="Paper B", arxiv_id="b"))
        await store.add_citation_edge(a, b)

        edges_from_a = await store.get_citation_edges(a)
        edges_from_b = await store.get_citation_edges(b)
        assert len(edges_from_a) == 1
        assert len(edges_from_b) == 1
        assert edges_from_a[0]["source_id"] == a
        assert edges_from_a[0]["target_id"] == b
        assert edges_from_a[0]["relationship_type"] == "cites"

    @pytest.mark.asyncio
    async def test_add_edge_idempotent(self, store):
        a = await store.upsert_citation(make_paper(title="Paper A", arxiv_id="a"))
        b = await store.upsert_citation(make_paper(title="Paper B", arxiv_id="b"))
        await store.add_citation_edge(a, b)
        await store.add_citation_edge(a, b)  # re-sighting the same edge
        await store.add_citation_edge(a, b)
        edges = await store.get_citation_edges(a)
        assert len(edges) == 1

    @pytest.mark.asyncio
    async def test_citation_subgraph_bfs_respects_max_depth(self, store):
        # Chain: A -> B -> C -> D
        ids = {}
        for label in ("A", "B", "C", "D"):
            ids[label] = await store.upsert_citation(
                make_paper(title=f"Paper {label}", arxiv_id=label)
            )
        await store.add_citation_edge(ids["A"], ids["B"])
        await store.add_citation_edge(ids["B"], ids["C"])
        await store.add_citation_edge(ids["C"], ids["D"])

        nodes, edges = await store.citation_subgraph([ids["A"]], max_depth=1)
        node_ids = {n["id"] for n in nodes}
        assert node_ids == {ids["A"], ids["B"]}
        # Edges collected while visiting B include B's far edge (B->C) even though C
        # itself isn't promoted to `visited` until the next depth step — same lag
        # behavior as the existing relevant_subgraphs() BFS over concept_relationships.
        assert len(edges) == 2

        nodes_deep, edges_deep = await store.citation_subgraph([ids["A"]], max_depth=3)
        assert {n["id"] for n in nodes_deep} == set(ids.values())
        assert len(edges_deep) == 3

    @pytest.mark.asyncio
    async def test_citation_subgraph_empty_seed(self, store):
        nodes, edges = await store.citation_subgraph([], max_depth=2)
        assert nodes == []
        assert edges == []


class TestInterestCitationLinks:
    @pytest.mark.asyncio
    async def test_link_and_get_citations_for_interest(self, store):
        now = "2026-06-23T00:00:00+00:00"
        await store.upsert_interest(
            {"id": "ml", "label": "machine learning", "strength": 0.8,
             "created_at": now, "updated_at": now, "last_active": now}
        )
        citation_id = await store.upsert_citation(make_paper())
        await store.link_interest_to_citation("ml", citation_id, relevance=0.9)

        linked = await store.get_citations_for_interest("ml")
        assert len(linked) == 1
        assert linked[0]["id"] == citation_id
        assert linked[0]["relevance"] == 0.9

    @pytest.mark.asyncio
    async def test_relink_updates_relevance_not_duplicate(self, store):
        now = "2026-06-23T00:00:00+00:00"
        await store.upsert_interest(
            {"id": "ml", "label": "machine learning", "strength": 0.8,
             "created_at": now, "updated_at": now, "last_active": now}
        )
        citation_id = await store.upsert_citation(make_paper())
        await store.link_interest_to_citation("ml", citation_id, relevance=0.5)
        await store.link_interest_to_citation("ml", citation_id, relevance=0.95)

        linked = await store.get_citations_for_interest("ml")
        assert len(linked) == 1
        assert linked[0]["relevance"] == 0.95


class TestGetExistingResearch:
    @pytest.mark.asyncio
    async def test_with_interest_id_uses_link_tables(self, store):
        now = "2026-06-23T00:00:00+00:00"
        await store.upsert_interest(
            {"id": "ml", "label": "machine learning", "strength": 0.8,
             "created_at": now, "updated_at": now, "last_active": now}
        )
        citation_id = await store.upsert_citation(make_paper())
        await store.link_interest_to_citation("ml", citation_id)
        run_id = await store.start_research_run({"topic": "machine learning", "interest_id": "ml"})
        await store.finish_research_run(run_id, papers_new=1)

        existing = await store.get_existing_research("machine learning", interest_id="ml")
        assert len(existing["runs"]) == 1
        assert len(existing["citations"]) == 1

    @pytest.mark.asyncio
    async def test_without_interest_id_falls_back_to_title_match(self, store):
        await store.upsert_citation(make_paper(title="Diffusion Models Beat GANs"))
        existing = await store.get_existing_research("Diffusion Models")
        assert len(existing["citations"]) == 1

    @pytest.mark.asyncio
    async def test_no_prior_research_returns_empty(self, store):
        existing = await store.get_existing_research("an unresearched topic")
        assert existing == {"runs": [], "citations": [], "concepts": []}


class TestResearchRuns:
    @pytest.mark.asyncio
    async def test_start_and_finish_run(self, store):
        run_id = await store.start_research_run({"topic": "rust", "depth": "deep"})
        runs = await store.get_research_runs(topic="rust")
        assert runs[0]["status"] == "running"

        await store.finish_research_run(run_id, papers_found=5, papers_new=3, summary="Found 3 new papers.")
        runs = await store.get_research_runs(topic="rust")
        assert runs[0]["status"] == "completed"
        assert runs[0]["papers_new"] == 3
        assert runs[0]["summary"] == "Found 3 new papers."
        assert runs[0]["completed_at"] is not None

    @pytest.mark.asyncio
    async def test_finish_run_with_error(self, store):
        run_id = await store.start_research_run({"topic": "rust"})
        await store.finish_research_run(run_id, status="failed", error="connector timeout")
        runs = await store.get_research_runs(topic="rust")
        assert runs[0]["status"] == "failed"
        assert runs[0]["error"] == "connector timeout"

    @pytest.mark.asyncio
    async def test_filter_by_interest_id(self, store):
        now = "2026-06-23T00:00:00+00:00"
        for interest_id in ("rust-interest", "other-interest"):
            await store.upsert_interest(
                {"id": interest_id, "label": interest_id, "strength": 0.5,
                 "created_at": now, "updated_at": now, "last_active": now}
            )
        await store.start_research_run({"topic": "rust", "interest_id": "rust-interest"})
        await store.start_research_run({"topic": "rust", "interest_id": "other-interest"})
        runs = await store.get_research_runs(interest_id="rust-interest")
        assert len(runs) == 1

    @pytest.mark.asyncio
    async def test_ordered_most_recent_first(self, store):
        first = await store.start_research_run({"topic": "rust"})
        await store.finish_research_run(first)
        second = await store.start_research_run({"topic": "rust"})
        await store.finish_research_run(second)
        runs = await store.get_research_runs(topic="rust")
        assert runs[0]["id"] == second
        assert runs[1]["id"] == first


class TestSchemaMigration:
    @pytest.mark.asyncio
    async def test_reopening_existing_db_is_idempotent(self, temp_db):
        """Re-running _create_tables against an already-migrated DB must not error
        or lose data (additive migration guarantee from data-model.md §8)."""
        kb1 = UnifiedKnowledgeStore(temp_db)
        await kb1.initialize()
        citation_id = await kb1.upsert_citation(make_paper())
        await kb1.close()

        kb2 = UnifiedKnowledgeStore(temp_db)
        await kb2.initialize()  # re-migrates the same file
        row = await kb2.get_citation(citation_id)
        assert row is not None
        assert row["title"] == "Attention Is All You Need"
        await kb2.close()

    @pytest.mark.asyncio
    async def test_citation_relationships_has_unique_constraint(self, store):
        cursor = await store._db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='citation_relationships'"
        )
        row = await cursor.fetchone()
        assert "UNIQUE" in row["sql"]
