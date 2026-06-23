"""OpenAlex connector — fallback citation source when Semantic Scholar is rate-limited.

OpenAlex (https://openalex.org) provides free access to academic metadata.
No authentication required, but accepts an API key (OPENALEX_API_KEY) for higher limits.
"""

import asyncio
import logging
import os
from typing import Any, Optional

import httpx

from .base import RawPaper

logger = logging.getLogger(__name__)

BASE_URL = "https://api.openalex.org"


def _paper_from_json(data: dict[str, Any]) -> RawPaper:
    """Normalize OpenAlex paper JSON to RawPaper."""
    # OpenAlex structure: title, abstract_inverted_index, authorships, publication_year, etc.
    authors = []
    for auth in data.get("authorships", []):
        author = auth.get("author", {})
        if author.get("display_name"):
            authors.append(author["display_name"])

    # Reconstruct abstract from inverted index (OpenAlex's compact format)
    abstract = None
    inverted_idx = data.get("abstract_inverted_index")
    if inverted_idx and isinstance(inverted_idx, dict):
        try:
            # Find max position to size the words array
            all_positions = []
            for positions in inverted_idx.values():
                if isinstance(positions, list):
                    all_positions.extend(positions)

            if all_positions:
                max_pos = max(all_positions)
                words = [""] * (max_pos + 1)
                # Populate words array: word at positions[i] goes to words[positions[i]]
                for word, positions in inverted_idx.items():
                    if isinstance(positions, list):
                        for pos in positions:
                            if isinstance(pos, int) and 0 <= pos <= max_pos:
                                words[pos] = word
                abstract = " ".join(words).strip()
        except (TypeError, ValueError, IndexError, AttributeError):
            abstract = None

    # Extract external IDs
    external_ids = data.get("ids", {})
    doi = external_ids.get("doi")
    if doi and doi.startswith("https://doi.org/"):
        doi = doi.replace("https://doi.org/", "")

    return RawPaper(
        title=data.get("title") or "",
        abstract=abstract,
        authors=authors,
        published_date=None,
        year=data.get("publication_year"),
        citation_count=data.get("cited_by_count", 0),
        reference_count=None,  # OpenAlex doesn't expose reference count in search
        url=data.get("url"),
        doi=doi,
        semantic_scholar_id=external_ids.get("semantic_scholar_id"),
        source="openalex",
    )


class OpenAlexConnector:
    """OpenAlex citation source (free, no auth required, but higher limits with API key)."""

    def __init__(self, config: Optional[dict[str, Any]] = None):
        config = config or {}
        self.api_key = config.get("openalex_api_key") or os.getenv("OPENALEX_API_KEY")
        self.max_retries = config.get("max_retries", 3)
        self.timeout = config.get("request_timeout", 30)

    def _headers(self) -> dict[str, str]:
        """Headers for OpenAlex (email + api key if present)."""
        headers = {
            "User-Agent": "PersonalAssistant/1.0 (https://github.com/diazoangga/personal-assistant)"
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    async def _get(self, path: str, params: dict[str, Any]) -> Optional[dict[str, Any]]:
        """GET request with exponential backoff on rate limits.

        Returns None on error (no exception) so research continues without Semantic Scholar.
        """
        url = f"{BASE_URL}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(self.max_retries):
                try:
                    response = await client.get(url, params=params, headers=self._headers())
                    response.raise_for_status()
                    return response.json()
                except httpx.HTTPStatusError as e:
                    # Rate limit: back off and retry
                    if e.response.status_code == 429 and attempt < self.max_retries - 1:
                        wait_time = (2**attempt) * 2
                        logger.warning(f"OpenAlex rate limited, waiting {wait_time}s")
                        await asyncio.sleep(wait_time)
                        continue
                    logger.warning(f"OpenAlex HTTP error {e.response.status_code}: {e}")
                    return None
                except httpx.HTTPError as e:
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(2**attempt)
                        continue
                    logger.warning(f"OpenAlex request failed: {e}")
                    return None
        return None

    async def search(self, topic: str, limit: int = 10) -> list[RawPaper]:
        """Search for papers matching a topic on OpenAlex.

        Args:
            topic: Search query (OpenAlex uses full-text search)
            limit: Max results to return

        Returns:
            List of RawPaper objects
        """
        # OpenAlex search: per_page limit is 50 (they accept per_page parameter)
        per_page = min(limit, 50)
        data = await self._get(
            "/works",
            {
                "search": topic,
                "per_page": per_page,
                "sort": "cited_by_count:desc",  # Sort by citation count
            },
        )
        if not data:
            return []

        papers = []
        for work in data.get("results", []):
            if work.get("title"):
                papers.append(_paper_from_json(work))
        return papers

    async def get_references(self, paper_id: str, limit: int = 50) -> list[RawPaper]:
        """Get papers cited BY this paper (its references).

        OpenAlex doesn't have a direct references endpoint in the public API,
        so we return empty (could be enhanced if needed).
        """
        # OpenAlex's referenced_works endpoint requires the full OpenAlex ID format (W1234...)
        # For now, we don't follow references via OpenAlex
        return []

    async def get_citations(self, paper_id: str, limit: int = 50) -> list[RawPaper]:
        """Get papers that cite this paper.

        OpenAlex doesn't have a direct citations endpoint in the public API,
        so we return empty (could be enhanced if needed).
        """
        # OpenAlex's cited_by endpoint requires the full OpenAlex ID format (W1234...)
        # For now, we don't follow citations via OpenAlex
        return []
