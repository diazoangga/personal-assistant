"""arXiv connector — supplementary source for fresh preprints.

arXiv has no reference/citation graph of its own (see G2 in
docs/research-agent.data-model.md); it only ever contributes search-result nodes,
never edges.
"""

import asyncio
import logging
from typing import Any, Optional

import arxiv

from .base import RawPaper

logger = logging.getLogger(__name__)


def _paper_from_result(result: "arxiv.Result") -> RawPaper:
    return RawPaper(
        title=(result.title or "").strip().replace("\n", " "),
        abstract=(result.summary or "").strip().replace("\n", " "),
        authors=[a.name for a in result.authors],
        published_date=result.published.date().isoformat() if result.published else None,
        categories=list(result.categories or []),
        url=result.entry_id,
        doi=result.doi,
        arxiv_id=result.get_short_id().split("v")[0],
        source="arxiv",
    )


class ArxivConnector:
    """Supplementary fresh-preprint source."""

    def __init__(self, config: Optional[dict[str, Any]] = None):
        self.config = config or {}

    async def search(self, topic: str, limit: int = 10) -> list[RawPaper]:
        """Search arXiv for papers matching a topic."""
        try:
            return await asyncio.to_thread(self._search_sync, topic, limit)
        except Exception as e:
            logger.warning(f"arXiv search failed for '{topic}': {e}")
            return []

    def _search_sync(self, topic: str, limit: int) -> list[RawPaper]:
        """The `arxiv` package's Client.results() is blocking; run it off the event loop."""
        client = arxiv.Client()
        search = arxiv.Search(query=topic, max_results=limit, sort_by=arxiv.SortCriterion.Relevance)
        return [_paper_from_result(r) for r in client.results(search)]
