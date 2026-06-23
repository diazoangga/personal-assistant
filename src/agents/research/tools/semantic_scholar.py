"""Semantic Scholar Graph API connector — primary citation source.

Provides paper search plus the reference/citation frontier (G2 in
docs/research-agent.data-model.md) that arXiv alone cannot supply.
"""

import asyncio
import logging
import os
from typing import Any, Optional

import httpx

from .base import RawPaper

logger = logging.getLogger(__name__)

BASE_URL = "https://api.semanticscholar.org/graph/v1"
PAPER_FIELDS = (
    "paperId,title,abstract,authors,year,venue,url,tldr,citationCount,"
    "referenceCount,influentialCitationCount,externalIds,publicationDate"
)


def _paper_from_json(data: dict[str, Any]) -> RawPaper:
    authors = [a.get("name", "") for a in (data.get("authors") or []) if a.get("name")]
    external_ids = data.get("externalIds") or {}
    tldr = data.get("tldr") or {}
    return RawPaper(
        title=data.get("title") or "",
        abstract=data.get("abstract"),
        authors=authors,
        published_date=data.get("publicationDate"),
        venue=data.get("venue"),
        year=data.get("year"),
        citation_count=data.get("citationCount") or 0,
        reference_count=data.get("referenceCount") or 0,
        influential_citation_count=data.get("influentialCitationCount") or 0,
        url=data.get("url"),
        tldr=tldr.get("text") if isinstance(tldr, dict) else None,
        doi=external_ids.get("DOI"),
        arxiv_id=external_ids.get("ArXiv"),
        semantic_scholar_id=data.get("paperId"),
        source="semantic_scholar",
    )


class SemanticScholarConnector:
    """Primary citation source: search + reference/citation frontier."""

    def __init__(self, config: Optional[dict[str, Any]] = None):
        config = config or {}
        self.api_key = config.get("semantic_scholar_api_key") or os.getenv(
            "SEMANTIC_SCHOLAR_API_KEY"
        )
        self.max_retries = config.get("max_retries", 3)
        self.timeout = config.get("request_timeout", 30)

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key} if self.api_key else {}

    async def _get(self, path: str, params: dict[str, Any]) -> Optional[dict[str, Any]]:
        """GET with exponential backoff on 429, matching OpenRouterRuntime's retry style.
        Returns None (rather than raising) on exhausted retries so a flaky Semantic
        Scholar call degrades to "no results" instead of failing the whole research run.
        """
        url = f"{BASE_URL}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(self.max_retries):
                try:
                    response = await client.get(url, params=params, headers=self._headers())
                    response.raise_for_status()
                    return response.json()
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429 and attempt < self.max_retries - 1:
                        wait_time = (2**attempt) * 2
                        logger.warning(f"Semantic Scholar rate limited, waiting {wait_time}s")
                        await asyncio.sleep(wait_time)
                        continue
                    logger.warning(f"Semantic Scholar HTTP error {e.response.status_code}: {e}")
                    return None
                except httpx.HTTPError as e:
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(2**attempt)
                        continue
                    logger.warning(f"Semantic Scholar request failed: {e}")
                    return None
        return None

    async def search(self, topic: str, limit: int = 10) -> list[RawPaper]:
        """Search for papers matching a topic."""
        data = await self._get(
            "/paper/search", {"query": topic, "limit": limit, "fields": PAPER_FIELDS}
        )
        if not data:
            return []
        return [_paper_from_json(p) for p in data.get("data", []) if p.get("title")]

    async def get_references(self, paper_id: str, limit: int = 50) -> list[RawPaper]:
        """Papers that `paper_id` cites — the outgoing edge of the citation graph."""
        data = await self._get(
            f"/paper/{paper_id}/references",
            {"limit": limit, "fields": f"citedPaper.{PAPER_FIELDS}"},
        )
        if not data:
            return []
        papers = []
        for item in data.get("data", []):
            cited = item.get("citedPaper")
            if cited and cited.get("title"):
                papers.append(_paper_from_json(cited))
        return papers

    async def get_citations(self, paper_id: str, limit: int = 50) -> list[RawPaper]:
        """Papers that cite `paper_id` — the incoming edge of the citation graph."""
        data = await self._get(
            f"/paper/{paper_id}/citations",
            {"limit": limit, "fields": f"citingPaper.{PAPER_FIELDS}"},
        )
        if not data:
            return []
        papers = []
        for item in data.get("data", []):
            citing = item.get("citingPaper")
            if citing and citing.get("title"):
                papers.append(_paper_from_json(citing))
        return papers
