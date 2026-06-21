"""Knowledge Graph - Citation and concept graphs for research."""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import aiosqlite
from aiosqlite import Connection

logger = logging.getLogger(__name__)


@dataclass
class CitationNode:
    """A paper/research artifact in the citation graph."""

    id: str  # DOI or arXiv ID
    title: str
    authors: list[str]
    venue: str | None
    year: int
    abstract: str
    url: str | None
    cited_by: list[str] = field(default_factory=list)  # IDs of papers citing this
    references: list[str] = field(default_factory=list)  # IDs of papers this references

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "authors": ",".join(self.authors),
            "venue": self.venue,
            "year": self.year,
            "abstract": self.abstract,
            "url": self.url,
            "cited_by": ",".join(self.cited_by),
            "references": ",".join(self.references),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CitationNode":
        return cls(
            id=data["id"],
            title=data["title"],
            authors=data.get("authors", "").split(",") if data.get("authors") else [],
            venue=data.get("venue"),
            year=data.get("year", 0),
            abstract=data.get("abstract", ""),
            url=data.get("url"),
            cited_by=data.get("cited_by", "").split(",") if data.get("cited_by") else [],
            references=data.get("references", "").split(",") if data.get("references") else [],
        )


@dataclass
class ConceptNode:
    """A concept/entity in the knowledge graph."""

    id: str
    label: str
    category: str  # "method", "task", "dataset", "metric", "domain"
    description: str | None
    aliases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "category": self.category,
            "description": self.description,
            "aliases": ",".join(self.aliases),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConceptNode":
        return cls(
            id=data["id"],
            label=data["label"],
            category=data.get("category", "unknown"),
            description=data.get("description"),
            aliases=data.get("aliases", "").split(",") if data.get("aliases") else [],
        )


@dataclass
class RelationEdge:
    """A relation between concept nodes."""

    source_id: str
    target_id: str
    relation_type: str  # "used_for", "extends", "evaluated_on", "compared_to"
    confidence: float = 1.0
    evidence: list[str] = field(default_factory=list)  # Source paper IDs

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation_type": self.relation_type,
            "confidence": self.confidence,
            "evidence": ",".join(self.evidence),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RelationEdge":
        return cls(
            source_id=data["source_id"],
            target_id=data["target_id"],
            relation_type=data["relation_type"],
            confidence=data.get("confidence", 1.0),
            evidence=data.get("evidence", "").split(",") if data.get("evidence") else [],
        )


class CitationGraph:
    """
    Citation graph for research papers.

    Tracks citations between papers for novelty detection and literature review.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._db: Connection | None = None

    async def initialize(self) -> None:
        """Initialize the database."""
        logger.debug(f"Initializing CitationGraph at {self.db_path}")
        self._db = await aiosqlite.connect(self.db_path)
        await self._create_tables()
        logger.info("CitationGraph initialized successfully")

    async def _create_tables(self) -> None:
        """Create tables."""
        assert self._db is not None
        logger.debug("Creating citation tables...")

        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS citation_nodes (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                authors TEXT,
                venue TEXT,
                year INTEGER,
                abstract TEXT,
                url TEXT,
                cited_by TEXT,
                "references" TEXT
            )
        """)

        # Link citations to concepts (evidence relationships)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS citation_concept_links (
                citation_id TEXT NOT NULL,
                concept_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                evidence_text TEXT,
                PRIMARY KEY (citation_id, concept_id),
                FOREIGN KEY (citation_id) REFERENCES citation_nodes(id),
                FOREIGN KEY (concept_id) REFERENCES concept_nodes(id)
            )
        """)

        await self._db.commit()
        logger.debug("Citation tables created")

    async def close(self) -> None:
        """Close the database."""
        if self._db:
            logger.debug("Closing CitationGraph database connection")
            await self._db.close()
            logger.info("CitationGraph database connection closed")

    async def add_paper(self, paper: CitationNode) -> None:
        """Add or update a paper."""
        assert self._db is not None
        await self._db.execute(
            """
            INSERT OR REPLACE INTO citation_nodes
            (id, title, authors, venue, year, abstract, url, cited_by, "references")
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paper.id,
                paper.title,
                ",".join(paper.authors),
                paper.venue,
                paper.year,
                paper.abstract,
                paper.url,
                ",".join(paper.cited_by),
                ",".join(paper.references),
            ),
        )
        await self._db.commit()

    async def get_paper(self, paper_id: str) -> CitationNode | None:
        """Get a paper by ID."""
        assert self._db is not None
        async with self._db.execute(
            "SELECT * FROM citation_nodes WHERE id = ?", (paper_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return CitationNode.from_dict(dict(zip(
                    ["id", "title", "authors", "venue", "year", "abstract", "url", "cited_by", "references"],
                    row
                )))
            return None

    async def citation_chain(
        self, paper_id: str, depth: int = 2
    ) -> list[CitationNode]:
        """
        Get the citation chain for a paper.

        Args:
            paper_id: Starting paper ID
            depth: How many hops to traverse

        Returns:
            List of all papers in the citation chain
        """
        assert self._db is not None
        visited = set()
        to_visit = [paper_id]
        result = []

        while to_visit and depth > 0:
            next_visit = []
            for pid in to_visit:
                if pid in visited:
                    continue
                visited.add(pid)

                paper = await self.get_paper(pid)
                if paper:
                    result.append(paper)
                    next_visit.extend(paper.references)
                    next_visit.extend(paper.cited_by)

            to_visit = next_visit
            depth -= 1

        return result

    async def is_novel(
        self, paper: CitationNode, similarity_threshold: float = 0.8
    ) -> bool:
        """
        Check if a paper is novel compared to existing papers.

        This is a stub - would use embeddings + similarity search in practice.
        """
        # Simple check: exact title match
        assert self._db is not None
        async with self._db.execute(
            "SELECT COUNT(*) FROM citation_nodes WHERE title = ?", (paper.title,)
        ) as cursor:
            count = await cursor.fetchone()
            return count[0] == 0 if count else True

    # Citation-Concept linking operations

    async def add_citation_concept_link(
        self,
        citation_id: str,
        concept_id: str,
        relation_type: str,
        evidence_text: str | None = None,
    ) -> None:
        """
        Link a citation to a concept node.
        
        Args:
            citation_id: ID of the paper (DOI/arXiv)
            concept_id: ID of the concept node
            relation_type: "introduces", "uses", "evaluates", "extends"
            evidence_text: Excerpt from paper supporting this link
        """
        assert self._db is not None
        
        await self._db.execute(
            """
            INSERT OR REPLACE INTO citation_concept_links
            (citation_id, concept_id, relation_type, evidence_text)
            VALUES (?, ?, ?, ?)
            """,
            (citation_id, concept_id, relation_type, evidence_text),
        )
        await self._db.commit()

    async def get_concepts_for_citation(self, citation_id: str) -> list[str]:
        """Get concept IDs linked to a citation."""
        assert self._db is not None
        
        async with self._db.execute(
            "SELECT concept_id FROM citation_concept_links WHERE citation_id = ?",
            (citation_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def get_citations_for_concept(self, concept_id: str) -> list[str]:
        """Get citation IDs linked to a concept."""
        assert self._db is not None
        
        async with self._db.execute(
            "SELECT citation_id FROM citation_concept_links WHERE concept_id = ?",
            (concept_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]


class KnowledgeGraph:
    """
    Knowledge graph for concepts and entities.

    Tracks relationships between methods, tasks, datasets, metrics, etc.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._db: Connection | None = None

    async def initialize(self) -> None:
        """Initialize the database."""
        logger.debug(f"Initializing KnowledgeGraph at {self.db_path}")
        self._db = await aiosqlite.connect(self.db_path)
        await self._create_tables()
        logger.info("KnowledgeGraph initialized successfully")

    async def _create_tables(self) -> None:
        """Create tables."""
        assert self._db is not None
        logger.debug("Creating knowledge graph tables...")

        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS concept_nodes (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT,
                aliases TEXT
            )
        """)

        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS relation_edges (
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                evidence TEXT,
                PRIMARY KEY (source_id, target_id, relation_type),
                FOREIGN KEY (source_id) REFERENCES concept_nodes(id),
                FOREIGN KEY (target_id) REFERENCES concept_nodes(id)
            )
        """)

        await self._db.commit()
        logger.debug("Knowledge graph tables created")

    async def close(self) -> None:
        """Close the database."""
        if self._db:
            logger.debug("Closing KnowledgeGraph database connection")
            await self._db.close()
            logger.info("KnowledgeGraph database connection closed")

    async def add_concept(self, concept: ConceptNode) -> None:
        """Add or update a concept."""
        assert self._db is not None
        await self._db.execute(
            """
            INSERT OR REPLACE INTO concept_nodes
            (id, label, category, description, aliases)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                concept.id,
                concept.label,
                concept.category,
                concept.description,
                ",".join(concept.aliases),
            ),
        )
        await self._db.commit()

    async def add_relation(self, edge: RelationEdge) -> None:
        """Add or update a relation."""
        assert self._db is not None
        await self._db.execute(
            """
            INSERT OR REPLACE INTO relation_edges
            (source_id, target_id, relation_type, confidence, evidence)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                edge.source_id,
                edge.target_id,
                edge.relation_type,
                edge.confidence,
                ",".join(edge.evidence),
            ),
        )
        await self._db.commit()

    async def get_concept(self, concept_id: str) -> ConceptNode | None:
        """Get a concept by ID."""
        assert self._db is not None
        async with self._db.execute(
            "SELECT * FROM concept_nodes WHERE id = ?", (concept_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return ConceptNode.from_dict(dict(zip(
                    ["id", "label", "category", "description", "aliases"],
                    row
                )))
            return None

    async def relevant_subgraphs(
        self, seed_ids: list[str], max_depth: int = 2
    ) -> tuple[list[ConceptNode], list[RelationEdge]]:
        """
        Extract a subgraph relevant to seed concepts.

        Args:
            seed_ids: Starting concept IDs
            max_depth: Maximum hops from seeds

        Returns:
            Tuple of (nodes, edges) in the subgraph
        """
        assert self._db is not None
        visited_nodes = set()
        visited_edges = set()
        nodes = []
        edges = []

        to_visit = list(seed_ids)
        depth = 0

        while to_visit and depth < max_depth:
            next_visit = []
            for cid in to_visit:
                if cid in visited_nodes:
                    continue
                visited_nodes.add(cid)

                concept = await self.get_concept(cid)
                if concept:
                    nodes.append(concept)

                # Get outgoing edges
                async with self._db.execute(
                    """
                    SELECT source_id, target_id, relation_type, confidence, evidence
                    FROM relation_edges WHERE source_id = ?
                    """,
                    (cid,),
                ) as cursor:
                    async for row in cursor:
                        edge_key = (row[0], row[1], row[2])
                        if edge_key not in visited_edges:
                            visited_edges.add(edge_key)
                            edges.append(RelationEdge.from_dict(dict(zip(
                                ["source_id", "target_id", "relation_type", "confidence", "evidence"],
                                row
                            ))))
                            if row[1] not in visited_nodes:
                                next_visit.append(row[1])

                # Get incoming edges
                async with self._db.execute(
                    """
                    SELECT source_id, target_id, relation_type, confidence, evidence
                    FROM relation_edges WHERE target_id = ?
                    """,
                    (cid,),
                ) as cursor:
                    async for row in cursor:
                        edge_key = (row[0], row[1], row[2])
                        if edge_key not in visited_edges:
                            visited_edges.add(edge_key)
                            edges.append(RelationEdge.from_dict(dict(zip(
                                ["source_id", "target_id", "relation_type", "confidence", "evidence"],
                                row
                            ))))
                            if row[0] not in visited_nodes:
                                next_visit.append(row[0])

            to_visit = next_visit
            depth += 1

        return nodes, edges

    async def find_concept_by_label(self, label: str) -> ConceptNode | None:
        """Find a concept by exact label match."""
        assert self._db is not None
        async with self._db.execute(
            "SELECT * FROM concept_nodes WHERE label = ?", (label,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return ConceptNode.from_dict(dict(zip(
                    ["id", "label", "category", "description", "aliases"],
                    row
                )))
            return None

    @staticmethod
    def compute_concept_id(label: str, category: str) -> str:
        """Compute a stable ID for a concept."""
        normalized = f"{category}:{label.lower().strip()}"
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    # Concept-Interest linking operations (cross-reference with UserMemory)
    # Note: The actual linking table is in UserMemory, this is a helper

    async def find_matching_concepts_for_interest(
        self, interest_label: str, min_similarity: float = 0.8
    ) -> list[tuple[str, float]]:
        """
        Find concept nodes that match an interest label.
        
        This uses exact match for now, can be enhanced with embeddings.
        
        Returns: [(concept_id, similarity_score), ...]
        """
        # Try exact match first
        concept = await self.find_concept_by_label(interest_label)
        if concept:
            return [(concept.id, 1.0)]
        
        # Try case-insensitive match
        async with self._db.execute(
            "SELECT id, label FROM concept_nodes WHERE LOWER(label) = LOWER(?)",
            (interest_label,)
        ) as cursor:
            rows = await cursor.fetchall()
            if rows:
                return [(row[0], 0.95) for row in rows]
        
        # Try fuzzy match (simple substring)
        async with self._db.execute(
            "SELECT id, label FROM concept_nodes WHERE label LIKE ?",
            (f"%{interest_label}%",)
        ) as cursor:
            rows = await cursor.fetchall()
            if rows:
                return [(row[0], 0.8) for row in rows]
        
        return []
