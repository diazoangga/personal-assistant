"""Tests for the Research Agent's source connectors (Semantic Scholar + arXiv + OpenAlex).

Network is mocked: Semantic Scholar and OpenAlex via httpx.MockTransport (deterministic canned
responses, no live calls), arXiv by monkeypatching arxiv.Client.results with real
arxiv.Result objects (exercises the actual normalization code, no network).
"""

from datetime import datetime, timezone

import arxiv
import httpx
import pytest

from src.agents.research.tools.arxiv_connector import ArxivConnector
from src.agents.research.tools.openalex_connector import OpenAlexConnector
from src.agents.research.tools.semantic_scholar import SemanticScholarConnector


def make_s2_connector(monkeypatch, handler) -> SemanticScholarConnector:
    """Route the connector's real httpx.AsyncClient calls through a MockTransport,
    so the actual _get() retry/error-handling logic is exercised, not bypassed."""
    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    class PatchedAsyncClient(real_async_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(
        "src.agents.research.tools.semantic_scholar.httpx.AsyncClient", PatchedAsyncClient
    )
    return SemanticScholarConnector()


class TestSemanticScholarConnector:
    @pytest.mark.asyncio
    async def test_search_normalizes_papers(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/graph/v1/paper/search"
            return httpx.Response(200, json={
                "data": [{
                    "paperId": "abc123",
                    "title": "Attention Is All You Need",
                    "abstract": "We propose the Transformer...",
                    "authors": [{"name": "Ashish Vaswani"}, {"name": "Noam Shazeer"}],
                    "year": 2017,
                    "venue": "NeurIPS",
                    "url": "https://www.semanticscholar.org/paper/abc123",
                    "tldr": {"text": "A new attention-only architecture."},
                    "citationCount": 100000,
                    "referenceCount": 50,
                    "influentialCitationCount": 9000,
                    "externalIds": {"DOI": "10.5555/xyz", "ArXiv": "1706.03762"},
                    "publicationDate": "2017-06-12",
                }]
            })

        connector = make_s2_connector(monkeypatch, handler)
        papers = await connector.search("transformers", limit=5)

        assert len(papers) == 1
        paper = papers[0]
        assert paper.title == "Attention Is All You Need"
        assert paper.authors == ["Ashish Vaswani", "Noam Shazeer"]
        assert paper.doi == "10.5555/xyz"
        assert paper.arxiv_id == "1706.03762"
        assert paper.semantic_scholar_id == "abc123"
        assert paper.tldr == "A new attention-only architecture."
        assert paper.source == "semantic_scholar"

    @pytest.mark.asyncio
    async def test_search_skips_entries_without_title(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"paperId": "x", "title": None}]})

        connector = make_s2_connector(monkeypatch, handler)
        papers = await connector.search("topic")
        assert papers == []

    @pytest.mark.asyncio
    async def test_search_returns_empty_on_persistent_error(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "server error"})

        connector = make_s2_connector(monkeypatch, handler)
        connector.max_retries = 1
        papers = await connector.search("topic")
        assert papers == []

    @pytest.mark.asyncio
    async def test_get_references_parses_cited_papers(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            assert "/references" in request.url.path
            return httpx.Response(200, json={
                "data": [
                    {"citedPaper": {"paperId": "ref1", "title": "Earlier Paper"}},
                    {"citedPaper": {"paperId": "ref2", "title": None}},  # dropped
                ]
            })

        connector = make_s2_connector(monkeypatch, handler)
        papers = await connector.get_references("abc123")
        assert len(papers) == 1
        assert papers[0].title == "Earlier Paper"
        assert papers[0].semantic_scholar_id == "ref1"

    @pytest.mark.asyncio
    async def test_get_citations_parses_citing_papers(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            assert "/citations" in request.url.path
            return httpx.Response(200, json={
                "data": [{"citingPaper": {"paperId": "cit1", "title": "Later Paper"}}]
            })

        connector = make_s2_connector(monkeypatch, handler)
        papers = await connector.get_citations("abc123")
        assert len(papers) == 1
        assert papers[0].title == "Later Paper"

    def test_headers_include_api_key_when_configured(self):
        connector = SemanticScholarConnector({"semantic_scholar_api_key": "secret"})
        assert connector._headers() == {"x-api-key": "secret"}

    def test_headers_empty_without_api_key(self):
        connector = SemanticScholarConnector({})
        connector.api_key = None
        assert connector._headers() == {}


def make_arxiv_result(arxiv_id: str, title: str, doi: str | None = None) -> arxiv.Result:
    return arxiv.Result(
        entry_id=f"http://arxiv.org/abs/{arxiv_id}v1",
        title=title,
        summary="A summary.\nWith a newline.",
        authors=[arxiv.Result.Author("Jane Doe"), arxiv.Result.Author("John Smith")],
        published=datetime(2024, 1, 15, tzinfo=timezone.utc),
        categories=["cs.LG"],
        doi=doi,
    )


class TestArxivConnector:
    @pytest.mark.asyncio
    async def test_search_normalizes_results(self, monkeypatch):
        result = make_arxiv_result("2401.00001", "A Fresh Preprint", doi="10.48550/arXiv.2401.00001")

        def fake_results(self, search):
            return [result]

        monkeypatch.setattr(arxiv.Client, "results", fake_results)

        connector = ArxivConnector()
        papers = await connector.search("some topic", limit=5)

        assert len(papers) == 1
        paper = papers[0]
        assert paper.title == "A Fresh Preprint"
        assert paper.arxiv_id == "2401.00001"
        assert paper.authors == ["Jane Doe", "John Smith"]
        assert paper.published_date == "2024-01-15"
        assert paper.categories == ["cs.LG"]
        assert paper.source == "arxiv"
        assert "\n" not in paper.abstract

    @pytest.mark.asyncio
    async def test_strips_version_suffix_from_arxiv_id(self, monkeypatch):
        result = make_arxiv_result("1706.03762", "Versioned Paper")

        def fake_results(self, search):
            return [result]

        monkeypatch.setattr(arxiv.Client, "results", fake_results)

        connector = ArxivConnector()
        papers = await connector.search("topic")
        assert papers[0].arxiv_id == "1706.03762"

    @pytest.mark.asyncio
    async def test_search_returns_empty_on_exception(self, monkeypatch):
        def fake_results(self, search):
            raise RuntimeError("network unreachable")

        monkeypatch.setattr(arxiv.Client, "results", fake_results)

        connector = ArxivConnector()
        papers = await connector.search("topic")
        assert papers == []


def make_openalex_connector(monkeypatch, handler) -> OpenAlexConnector:
    """Route the connector's httpx.AsyncClient through a MockTransport."""
    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    class PatchedAsyncClient(real_async_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(
        "src.agents.research.tools.openalex_connector.httpx.AsyncClient", PatchedAsyncClient
    )
    return OpenAlexConnector()


class TestOpenAlexConnector:
    @pytest.mark.asyncio
    async def test_search_normalizes_papers(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/works"
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "Deep Learning Foundations",
                            "publication_year": 2023,
                            "ids": {"doi": "https://doi.org/10.5555/abc"},
                            "authorships": [
                                {"author": {"display_name": "John Doe"}},
                                {"author": {"display_name": "Jane Smith"}},
                            ],
                            "cited_by_count": 50,
                            "url": "https://openalex.org/W1234567890",
                            "abstract_inverted_index": {
                                "deep": [0],
                                "learning": [1],
                                "is": [2],
                                "important": [3],
                            },
                        }
                    ]
                },
            )

        connector = make_openalex_connector(monkeypatch, handler)
        papers = await connector.search("deep learning", limit=5)

        assert len(papers) == 1
        paper = papers[0]
        assert paper.title == "Deep Learning Foundations"
        assert paper.year == 2023
        assert paper.authors == ["John Doe", "Jane Smith"]
        assert paper.citation_count == 50
        assert paper.source == "openalex"

    @pytest.mark.asyncio
    async def test_search_handles_missing_fields(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "Minimal Paper",
                            # No publication_year, no authorships, no abstract
                        }
                    ]
                },
            )

        connector = make_openalex_connector(monkeypatch, handler)
        papers = await connector.search("topic")

        assert len(papers) == 1
        assert papers[0].title == "Minimal Paper"
        assert papers[0].year is None
        assert papers[0].authors == []

    @pytest.mark.asyncio
    async def test_search_reconstructs_abstract_from_inverted_index(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "Test Paper",
                            "abstract_inverted_index": {
                                "this": [0],
                                "is": [1],
                                "a": [2],
                                "test": [3],
                            },
                        }
                    ]
                },
            )

        connector = make_openalex_connector(monkeypatch, handler)
        papers = await connector.search("topic")

        assert papers[0].abstract == "this is a test"

    @pytest.mark.asyncio
    async def test_citations_and_references_return_empty(self, monkeypatch):
        """OpenAlex doesn't expose citation/reference endpoints, so these return []."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        connector = make_openalex_connector(monkeypatch, handler)

        refs = await connector.get_references("W1234567890")
        cites = await connector.get_citations("W1234567890")

        assert refs == []
        assert cites == []
