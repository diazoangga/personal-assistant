"""Shared types and protocol for research source connectors."""

import json
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


@dataclass
class RawPaper:
    """Normalized paper shape produced by any research connector."""

    title: str
    abstract: Optional[str] = None
    authors: list[str] = field(default_factory=list)
    published_date: Optional[str] = None
    journal: Optional[str] = None
    venue: Optional[str] = None
    year: Optional[int] = None
    categories: list[str] = field(default_factory=list)
    citation_count: int = 0
    reference_count: int = 0
    influential_citation_count: int = 0
    url: Optional[str] = None
    tldr: Optional[str] = None
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    semantic_scholar_id: Optional[str] = None
    source: str = ""

    def to_citation_dict(self) -> dict[str, Any]:
        """Shape expected by `UnifiedKnowledgeStore.upsert_citation`."""
        return {
            "title": self.title,
            "abstract": self.abstract,
            "authors": json.dumps(self.authors),
            "published_date": self.published_date,
            "journal": self.journal,
            "venue": self.venue,
            "year": self.year,
            "categories": json.dumps(self.categories),
            "citation_count": self.citation_count,
            "reference_count": self.reference_count,
            "influential_citation_count": self.influential_citation_count,
            "url": self.url,
            "tldr": self.tldr,
            "doi": self.doi,
            "arxiv_id": self.arxiv_id,
            "semantic_scholar_id": self.semantic_scholar_id,
            "source": self.source,
        }


class ResearchConnector(Protocol):
    """A source that can be searched for papers on a topic."""

    async def search(self, topic: str, limit: int = 10) -> list[RawPaper]:
        ...
