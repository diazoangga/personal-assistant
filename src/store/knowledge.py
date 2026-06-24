"""Unified knowledge store - merges memory, citations, and concept graphs into database (SQLite or PostgreSQL)."""

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .db_connection import DBConnection, create_connection


def utcnow() -> datetime:
    """Get current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)

logger = logging.getLogger(__name__)


def compute_concept_id(label: str, category: str = "general") -> str:
    """Content-addressed concept ID, stable across re-extraction of the same concept."""
    key = f"{category}:{label.lower().strip()}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def compute_citation_id(citation: dict[str, Any]) -> str:
    """Content-addressed citation ID: doi > arxiv_id > semantic_scholar_id > title hash.

    This priority only matters for a brand-new paper; `_resolve_citation_id` checks
    existing rows by any of the three identifiers first, so a paper rediscovered via a
    second source backfills the existing row instead of minting a duplicate.
    """
    for field, prefix in (("doi", "doi"), ("arxiv_id", "arxiv"), ("semantic_scholar_id", "s2")):
        value = (citation.get(field) or "").strip().lower()
        if value:
            return f"{prefix}:{hashlib.sha256(value.encode()).hexdigest()[:16]}"
    title = (citation.get("title") or "").strip().lower()
    return f"title:{hashlib.sha256(title.encode()).hexdigest()[:16]}"


class UnifiedKnowledgeStore:
    """
    Unified knowledge store that consolidates:
    - User memory (interests, profile, opportunities)
    - Citation graph (research papers)
    - Knowledge graph (concepts and relationships)

    Supports both SQLite and PostgreSQL backends via DBConnection abstraction.
    All cross-references are maintained via linking tables.
    """

    def __init__(self, db: Optional[DBConnection] = None, db_type: str = "sqlite", **kwargs):
        """Initialize store with database connection.

        Args:
            db: Existing DBConnection instance (takes precedence)
            db_type: "sqlite" or "postgresql" (used to create connection if db is None)
            **kwargs: Connection parameters (db_path for sqlite, host/port/user/password for postgresql)
        """
        if db is not None:
            self._db = db
        else:
            self._db = create_connection(db_type, **kwargs)

    def _is_sqlite(self) -> bool:
        """Check if using SQLite backend (vs PostgreSQL)."""
        from .db_connection import SQLiteConnection
        return isinstance(self._db, SQLiteConnection)

    async def initialize(self) -> None:
        """Initialize database connection and create tables."""
        logger.info(f"Initializing unified knowledge store...")

        await self._db.initialize()

        # Create all tables (SQLite only; PostgreSQL schema already created via init_postgres_schema.py)
        if self._is_sqlite():
            await self._create_tables()
        else:
            logger.info("Using PostgreSQL backend (schema pre-created)")

        logger.info("Unified knowledge store initialized successfully")

    async def _add_column_if_missing(self, table: str, column: str, ddl: str) -> None:
        """Idempotently add a column to an existing table (SQLite only, for backward compat).

        PostgreSQL schema is created fully up-to-date via init_postgres_schema.py,
        so this additive migration only applies to SQLite databases.
        """
        if not self._is_sqlite():
            return
        try:
            rows = await self._db.fetchall(f"PRAGMA table_info({table})")
            existing = {row["name"] for row in rows}
            if column not in existing:
                await self._db.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
        except Exception:
            logger.warning(f"Could not check/add column {table}.{column}", exc_info=True)

    async def _migrate_citation_relationships(self) -> None:
        """Recreate citation_relationships with a UNIQUE edge constraint (SQLite only).

        The table previously had no UNIQUE(source_id, target_id, relationship_type), so
        re-research would duplicate edges. SQLite can't ALTER a UNIQUE constraint in, so an
        old-shape table is renamed, recreated, and its rows are copied over (deduplicated).

        PostgreSQL doesn't need this migration (schema is created correctly via init script).
        """
        if not self._is_sqlite():
            return

        row = await self._db.fetchone(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='citation_relationships'"
        )
        if row is None or "UNIQUE" in (row["sql"] or ""):
            return  # doesn't exist yet, or already migrated

        await self._db.execute(
            "ALTER TABLE citation_relationships RENAME TO citation_relationships_old"
        )
        await self._db.execute("""
            CREATE TABLE citation_relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relationship_type TEXT NOT NULL DEFAULT 'cites',
                UNIQUE(source_id, target_id, relationship_type),
                FOREIGN KEY (source_id) REFERENCES citations(id),
                FOREIGN KEY (target_id) REFERENCES citations(id)
            )
        """)
        await self._db.execute("""
            INSERT OR IGNORE INTO citation_relationships (source_id, target_id, relationship_type)
            SELECT source_id, target_id, COALESCE(relationship_type, 'cites')
            FROM citation_relationships_old
        """)
        await self._db.execute("DROP TABLE citation_relationships_old")
        await self._db.commit()

    async def _create_tables(self) -> None:
        """Create all unified schema tables."""

        # ===== USER MEMORY TABLES =====
        
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS interests (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                strength REAL DEFAULT 0.5,
                embeddings_cached INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_active TEXT
            )
        """)
        
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS interest_embeddings (
                interest_id TEXT PRIMARY KEY,
                embedding BLOB NOT NULL,
                model_version TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (interest_id) REFERENCES interests(id) ON DELETE CASCADE
            )
        """)
        
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS user_profile (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS opportunities (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                relevance_score REAL DEFAULT 0.5,
                source TEXT,
                url TEXT,
                created_at TEXT NOT NULL,
                metadata TEXT
            )
        """)
        
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                activity_type TEXT NOT NULL,
                description TEXT,
                raw_data TEXT
            )
        """)
        
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS interest_signal_evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id TEXT NOT NULL,
                topic TEXT NOT NULL,
                confidence REAL NOT NULL,
                timestamp TEXT NOT NULL,
                UNIQUE(signal_id, topic)
            )
        """)
        
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS interest_research_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT UNIQUE NOT NULL,
                last_researched_at TEXT NOT NULL
            )
        """)
        
        # ===== CITATION GRAPH TABLES =====
        
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS citations (
                id TEXT PRIMARY KEY,
                arxiv_id TEXT UNIQUE,
                doi TEXT UNIQUE,
                title TEXT NOT NULL,
                abstract TEXT,
                authors TEXT,  -- JSON array
                published_date TEXT,
                journal TEXT,
                categories TEXT,  -- JSON array
                citation_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)

        # Citation-graph node enrichment (research-agent.data-model.md §4.1)
        await self._add_column_if_missing("citations", "semantic_scholar_id", "semantic_scholar_id TEXT")
        await self._add_column_if_missing("citations", "url", "url TEXT")
        await self._add_column_if_missing("citations", "tldr", "tldr TEXT")
        await self._add_column_if_missing("citations", "conclusion", "conclusion TEXT")
        await self._add_column_if_missing("citations", "notes", "notes TEXT")
        await self._add_column_if_missing("citations", "year", "year INTEGER")
        await self._add_column_if_missing("citations", "venue", "venue TEXT")
        await self._add_column_if_missing("citations", "reference_count", "reference_count INTEGER DEFAULT 0")
        await self._add_column_if_missing(
            "citations", "influential_citation_count", "influential_citation_count INTEGER DEFAULT 0"
        )
        await self._add_column_if_missing("citations", "source", "source TEXT")
        await self._add_column_if_missing("citations", "last_researched_at", "last_researched_at TEXT")
        await self._add_column_if_missing("citations", "embedding_cached", "embedding_cached INTEGER DEFAULT 0")

        # Recreate citation_relationships with a UNIQUE edge constraint if it predates one.
        await self._migrate_citation_relationships()
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS citation_relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relationship_type TEXT NOT NULL DEFAULT 'cites',
                UNIQUE(source_id, target_id, relationship_type),
                FOREIGN KEY (source_id) REFERENCES citations(id),
                FOREIGN KEY (target_id) REFERENCES citations(id)
            )
        """)

        # ===== KNOWLEDGE GRAPH TABLES =====

        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS concepts (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                description TEXT,
                category TEXT,
                created_at TEXT NOT NULL
            )
        """)
        await self._add_column_if_missing("concepts", "mention_count", "mention_count INTEGER DEFAULT 0")
        await self._add_column_if_missing("concepts", "first_seen_run_id", "first_seen_run_id TEXT")
        
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS concept_relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                weight REAL DEFAULT 1.0,
                FOREIGN KEY (source_id) REFERENCES concepts(id),
                FOREIGN KEY (target_id) REFERENCES concepts(id)
            )
        """)
        
        # ===== CROSS-REFERENCE TABLES =====
        
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS interest_concept_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                interest_id TEXT NOT NULL,
                concept_id TEXT NOT NULL,
                link_type TEXT DEFAULT 'related',
                confidence REAL DEFAULT 0.8,
                created_at TEXT NOT NULL,
                FOREIGN KEY (interest_id) REFERENCES interests(id) ON DELETE CASCADE,
                FOREIGN KEY (concept_id) REFERENCES concepts(id) ON DELETE CASCADE,
                UNIQUE(interest_id, concept_id)
            )
        """)
        
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS citation_concept_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                citation_id TEXT NOT NULL,
                concept_id TEXT NOT NULL,
                relation_type TEXT DEFAULT 'discusses',
                evidence_text TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (citation_id) REFERENCES citations(id) ON DELETE CASCADE,
                FOREIGN KEY (concept_id) REFERENCES concepts(id) ON DELETE CASCADE,
                UNIQUE(citation_id, concept_id)
            )
        """)
        
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS interest_citation_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                interest_id TEXT NOT NULL,
                citation_id TEXT NOT NULL,
                relevance REAL DEFAULT 0.5,
                discovered_run_id TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (interest_id) REFERENCES interests(id) ON DELETE CASCADE,
                FOREIGN KEY (citation_id) REFERENCES citations(id) ON DELETE CASCADE,
                UNIQUE(interest_id, citation_id)
            )
        """)

        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS research_runs (
                id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                interest_id TEXT,
                trigger_source TEXT NOT NULL,
                depth TEXT NOT NULL,
                status TEXT NOT NULL,
                papers_found INTEGER DEFAULT 0,
                papers_new INTEGER DEFAULT 0,
                concepts_extracted INTEGER DEFAULT 0,
                concepts_new INTEGER DEFAULT 0,
                relationships_found INTEGER DEFAULT 0,
                summary TEXT,
                error TEXT,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY (interest_id) REFERENCES interests(id) ON DELETE SET NULL
            )
        """)

        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS opportunity_interest_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                opportunity_id TEXT NOT NULL,
                interest_id TEXT NOT NULL,
                relevance_score REAL DEFAULT 0.5,
                created_at TEXT NOT NULL,
                FOREIGN KEY (opportunity_id) REFERENCES opportunities(id) ON DELETE CASCADE,
                FOREIGN KEY (interest_id) REFERENCES interests(id) ON DELETE CASCADE,
                UNIQUE(opportunity_id, interest_id)
            )
        """)
        
        # ===== CONVERSATION HISTORY TABLES =====
        
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS conversation_sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                question_count INTEGER DEFAULT 0,
                metadata TEXT
            )
        """)
        
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS conversation_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                turn_number INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                metadata TEXT,
                FOREIGN KEY (session_id) REFERENCES conversation_sessions(id) ON DELETE CASCADE
            )
        """)
        
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_entries (
                id TEXT PRIMARY KEY,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                quality_score REAL DEFAULT 0.5,
                source_session_id TEXT,
                user_id TEXT NOT NULL,
                embedded INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                metadata TEXT,
                FOREIGN KEY (source_session_id) REFERENCES conversation_sessions(id) ON DELETE SET NULL
            )
        """)
        
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id TEXT PRIMARY KEY,
                total_questions INTEGER DEFAULT 0,
                total_knowledge_entries INTEGER DEFAULT 0,
                last_active TEXT,
                updated_at TEXT NOT NULL
            )
        """)
        
        # Create indexes for performance
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_interests_strength ON interests(strength)")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_interests_label ON interests(label)")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_concepts_label ON concepts(label)")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_citations_published ON citations(published_date)")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_interest_concept ON interest_concept_links(interest_id)")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_citation_concept ON citation_concept_links(citation_id)")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_citation_rel_source ON citation_relationships(source_id)")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_citation_rel_target ON citation_relationships(target_id)")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_interest_citation ON interest_citation_links(interest_id)")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_research_runs_topic ON research_runs(topic)")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_research_runs_interest ON research_runs(interest_id)")

        # Conversation and knowledge indexes
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_conversation_sessions_user ON conversation_sessions(user_id)")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_conversation_turns_session ON conversation_turns(session_id)")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_entries_user ON knowledge_entries(user_id)")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_entries_quality ON knowledge_entries(quality_score DESC)")
        
        await self._db.commit()

    async def close(self) -> None:
        """Close database connection."""
        if self._db:
            await self._db.close()
            self._db = None
            logger.info("Unified knowledge store closed")

    # ========== INTEREST METHODS ==========

    async def upsert_interest(self, node: dict[str, Any]) -> None:
        """Insert or update an interest."""
        now = utcnow().isoformat()
        
        await self._db.execute("""
            INSERT INTO interests (id, label, strength, created_at, updated_at, last_active)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                strength = excluded.strength,
                updated_at = excluded.updated_at,
                last_active = excluded.last_active
        """, (
            node.get("id"),
            node.get("label"),
            node.get("strength", 0.5),
            node.get("created_at", now),
            now,
            node.get("last_active", now),
        ))
        await self._db.commit()

    async def get_interest(self, interest_id: str) -> Optional[dict[str, Any]]:
        """Get a single interest by ID."""
        row = await self._db.fetchone(
            "SELECT * FROM interests WHERE id = ?",
            (interest_id,),
        )
        return dict(row) if row else None

    async def get_interests(self, min_strength: float = 0.0) -> list[dict[str, Any]]:
        """Get all interests above minimum strength threshold."""
        rows = await self._db.fetchall(
            "SELECT * FROM interests WHERE strength >= ? ORDER BY strength DESC",
            (min_strength,),
        )
        return [dict(row) for row in rows]

    async def delete_interest(self, interest_id: str) -> None:
        """Delete an interest."""
        await self._db.execute(
            "DELETE FROM interests WHERE id = ?",
            (interest_id,),
        )
        await self._db.commit()

    # ========== EMBEDDING CACHE METHODS ==========

    async def upsert_interest_embedding(
        self, interest_id: str, embedding: bytes, model_version: str
    ) -> None:
        """Cache embedding for an interest."""
        now = utcnow().isoformat()
        
        await self._db.execute("""
            INSERT INTO interest_embeddings (interest_id, embedding, model_version, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(interest_id) DO UPDATE SET
                embedding = excluded.embedding,
                model_version = excluded.model_version,
                updated_at = excluded.updated_at
        """, (interest_id, embedding, model_version, now))
        
        # Mark interest as having cached embeddings
        await self._db.execute(
            "UPDATE interests SET embeddings_cached = 1 WHERE id = ?",
            (interest_id,),
        )
        await self._db.commit()

    async def get_interest_embedding(self, interest_id: str) -> Optional[bytes]:
        """Get cached embedding for an interest."""
        row = await self._db.fetchone(
            "SELECT embedding FROM interest_embeddings WHERE interest_id = ?",
            (interest_id,),
        )
        return row["embedding"] if row else None

    async def get_all_interest_embeddings(self) -> list[tuple[str, bytes]]:
        """Get all cached interest embeddings with their IDs."""
        rows = await self._db.fetchall(
            "SELECT ie.interest_id, ie.embedding, i.label "
            "FROM interest_embeddings ie "
            "JOIN interests i ON ie.interest_id = i.id"
        )
        return [(row["interest_id"], row["embedding"], row["label"]) for row in rows]

    async def get_interest_embeddings(self, min_strength: float = 0.2) -> list[tuple[str, bytes, str]]:
        """Get embeddings for interests above minimum strength threshold.
        
        Returns list of (interest_id, embedding_bytes, label) tuples.
        """
        rows = await self._db.fetchall("""
            SELECT ie.interest_id, ie.embedding, i.label
            FROM interest_embeddings ie
            JOIN interests i ON ie.interest_id = i.id
            WHERE i.strength >= ?
            ORDER BY i.strength DESC
        """, (min_strength,))
        return [(row["interest_id"], row["embedding"], row["label"]) for row in rows]

    # ========== CONCEPT METHODS ==========

    async def upsert_concept(self, concept: dict[str, Any]) -> None:
        """Insert or update a concept."""
        now = utcnow().isoformat()
        
        await self._db.execute("""
            INSERT INTO concepts (id, label, description, category, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                description = excluded.description,
                category = excluded.category
        """, (
            concept.get("id"),
            concept.get("label"),
            concept.get("description"),
            concept.get("category"),
            concept.get("created_at", now),
        ))
        await self._db.commit()

    async def get_concept(self, concept_id: str) -> Optional[dict[str, Any]]:
        """Get a concept by ID."""
        row = await self._db.fetchone(
            "SELECT * FROM concepts WHERE id = ?",
            (concept_id,),
        )
        return dict(row) if row else None

    async def get_all_concepts(self) -> list[dict[str, Any]]:
        """Get all concepts."""
        rows = await self._db.fetchall("SELECT * FROM concepts ORDER BY label")
        return [dict(row) for row in rows]

    async def find_concepts_by_label(self, label_pattern: str) -> list[dict[str, Any]]:
        """Find concepts matching label pattern (SQL LIKE)."""
        rows = await self._db.fetchall(
            "SELECT * FROM concepts WHERE label LIKE ? OR label = ?",
            (f"%{label_pattern}%", label_pattern),
        )
        return [dict(row) for row in rows]

    # ========== CONCEPT RELATIONSHIP / GRAPH TRAVERSAL METHODS ==========

    async def add_concept_relationship(
        self, source_id: str, target_id: str, relation_type: str, weight: float = 1.0
    ) -> None:
        """Insert or update a relationship edge between two concepts."""
        row = await self._db.fetchone(
            "SELECT id FROM concept_relationships WHERE source_id = ? AND target_id = ? AND relation_type = ?",
            (source_id, target_id, relation_type),
        )
        if row:
            await self._db.execute(
                "UPDATE concept_relationships SET weight = ? WHERE id = ?",
                (weight, row["id"]),
            )
        else:
            await self._db.execute(
                """
                INSERT INTO concept_relationships (source_id, target_id, relation_type, weight)
                VALUES (?, ?, ?, ?)
                """,
                (source_id, target_id, relation_type, weight),
            )
        await self._db.commit()

    async def get_concept_relationships(self, concept_id: str) -> list[dict[str, Any]]:
        """Get all relationship edges touching a concept, in either direction."""
        rows = await self._db.fetchall(
            "SELECT * FROM concept_relationships WHERE source_id = ? OR target_id = ?",
            (concept_id, concept_id),
        )
        return [dict(row) for row in rows]

    async def relevant_subgraphs(
        self,
        seed_ids: Optional[list[str]] = None,
        interests: Optional[list[str]] = None,
        max_depth: int = 2,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """BFS over concept_relationships from seed concept IDs (or interest labels) up to max_depth.

        Returns (nodes, edges) where nodes are concept dicts and edges are relationship dicts.
        """
        seeds: set[str] = set(seed_ids or [])
        for label in interests or []:
            for concept in await self.find_concepts_by_label(label):
                seeds.add(concept["id"])

        if not seeds:
            return [], []

        visited: set[str] = set()
        frontier: set[str] = set(seeds)
        edges_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}

        depth = 0
        while frontier and depth <= max_depth:
            next_frontier: set[str] = set()
            for concept_id in frontier:
                if concept_id in visited:
                    continue
                visited.add(concept_id)

                for edge in await self.get_concept_relationships(concept_id):
                    key = (edge["source_id"], edge["target_id"], edge["relation_type"])
                    edges_by_key[key] = edge
                    for neighbor in (edge["source_id"], edge["target_id"]):
                        if neighbor not in visited:
                            next_frontier.add(neighbor)

            frontier = next_frontier
            depth += 1

        nodes = []
        for concept_id in visited:
            concept = await self.get_concept(concept_id)
            if concept:
                nodes.append(concept)

        return nodes, list(edges_by_key.values())

    # ========== CITATION METHODS ==========

    async def _resolve_citation_id(self, citation: dict[str, Any]) -> str:
        """Find an existing citation by any cross-source identifier before minting a new ID.

        Each source (Semantic Scholar, arXiv) may only populate one of doi/arxiv_id/
        semantic_scholar_id; checking all three against existing rows is what lets a paper
        rediscovered via a second source update its existing row instead of duplicating it.
        """
        for field in ("doi", "arxiv_id", "semantic_scholar_id"):
            value = citation.get(field)
            if value:
                row = await self._db.fetchone(f"SELECT id FROM citations WHERE {field} = ?", (value,))
                if row:
                    return row["id"]
        return compute_citation_id(citation)

    async def upsert_citation(self, citation: dict[str, Any]) -> str:
        """Insert or update a citation. Returns the resolved citation_id.

        If `citation["id"]` is given explicitly, it's used as-is (caller already decided
        identity, e.g. brainstorming's web-search registrations). Otherwise identity is
        resolved via `_resolve_citation_id` so re-research backfills rather than duplicates.
        """
        now = utcnow().isoformat()
        citation_id = citation.get("id") or await self._resolve_citation_id(citation)
        notes = citation.get("notes")
        notes_json = json.dumps(notes) if isinstance(notes, dict) else notes

        await self._db.execute("""
            INSERT INTO citations (
                id, arxiv_id, doi, semantic_scholar_id, title, abstract, authors,
                published_date, journal, venue, year, categories, citation_count,
                reference_count, influential_citation_count, url, tldr, conclusion,
                notes, source, last_researched_at, embedding_cached, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                arxiv_id = COALESCE(excluded.arxiv_id, citations.arxiv_id),
                doi = COALESCE(excluded.doi, citations.doi),
                semantic_scholar_id = COALESCE(excluded.semantic_scholar_id, citations.semantic_scholar_id),
                title = excluded.title,
                abstract = COALESCE(excluded.abstract, citations.abstract),
                authors = COALESCE(excluded.authors, citations.authors),
                published_date = COALESCE(excluded.published_date, citations.published_date),
                journal = COALESCE(excluded.journal, citations.journal),
                venue = COALESCE(excluded.venue, citations.venue),
                year = COALESCE(excluded.year, citations.year),
                categories = COALESCE(excluded.categories, citations.categories),
                citation_count = excluded.citation_count,
                reference_count = excluded.reference_count,
                influential_citation_count = excluded.influential_citation_count,
                url = COALESCE(excluded.url, citations.url),
                tldr = COALESCE(excluded.tldr, citations.tldr),
                conclusion = COALESCE(excluded.conclusion, citations.conclusion),
                notes = COALESCE(excluded.notes, citations.notes),
                source = COALESCE(excluded.source, citations.source),
                last_researched_at = COALESCE(excluded.last_researched_at, citations.last_researched_at)
        """, (
            citation_id,
            citation.get("arxiv_id"),
            citation.get("doi"),
            citation.get("semantic_scholar_id"),
            citation.get("title"),
            citation.get("abstract"),
            citation.get("authors"),  # JSON string
            citation.get("published_date"),
            citation.get("journal"),
            citation.get("venue"),
            citation.get("year"),
            citation.get("categories"),  # JSON string
            citation.get("citation_count", 0),
            citation.get("reference_count", 0),
            citation.get("influential_citation_count", 0),
            citation.get("url"),
            citation.get("tldr"),
            citation.get("conclusion"),
            notes_json,
            citation.get("source"),
            citation.get("last_researched_at"),
            citation.get("embedding_cached", 0),
            now,
        ))
        await self._db.commit()
        return citation_id

    async def get_citation(self, citation_id: str) -> Optional[dict[str, Any]]:
        """Get a citation by ID."""
        row = await self._db.fetchone(
            "SELECT * FROM citations WHERE id = ?",
            (citation_id,),
        )
        return dict(row) if row else None

    async def get_all_citations(self) -> list[dict[str, Any]]:
        """Get all citations."""
        rows = await self._db.fetchall("SELECT * FROM citations ORDER BY published_date DESC")
        return [dict(row) for row in rows]

    async def find_citations_by_title(self, pattern: str) -> list[dict[str, Any]]:
        """Find citations with a title matching pattern (SQL LIKE) — fallback lookup
        when a topic has no linked interest to query through."""
        rows = await self._db.fetchall(
            "SELECT * FROM citations WHERE title LIKE ?",
            (f"%{pattern}%",),
        )
        return [dict(row) for row in rows]

    async def update_citation_notes(
        self, citation_id: str, *, conclusion: Optional[str] = None, notes: Optional[dict[str, Any]] = None
    ) -> None:
        """Update the LLM-synthesized conclusion and/or structured notes for a citation."""
        notes_json = json.dumps(notes) if notes is not None else None
        await self._db.execute(
            "UPDATE citations SET conclusion = COALESCE(?, conclusion), notes = COALESCE(?, notes) WHERE id = ?",
            (conclusion, notes_json, citation_id),
        )
        await self._db.commit()

    async def is_known_citation(self, citation_id: str) -> bool:
        """Whether a citation already exists — the novelty gate for citation-chase BFS."""
        row = await self._db.fetchone("SELECT 1 FROM citations WHERE id = ?", (citation_id,))
        return row is not None

    # ========== CITATION GRAPH (cites edges) ==========

    async def add_citation_edge(self, source_id: str, target_id: str, relationship_type: str = "cites") -> None:
        """Insert a directed citation edge (source cites target). Idempotent: a second
        sighting of the same edge is a no-op rather than a duplicate row."""
        await self._db.execute(
            """
            INSERT INTO citation_relationships (source_id, target_id, relationship_type)
            VALUES (?, ?, ?)
            ON CONFLICT(source_id, target_id, relationship_type) DO NOTHING
            """,
            (source_id, target_id, relationship_type),
        )
        await self._db.commit()

    async def get_citation_edges(self, citation_id: str) -> list[dict[str, Any]]:
        """Get all citation edges touching a paper, in either direction (cites / cited-by)."""
        rows = await self._db.fetchall(
            "SELECT * FROM citation_relationships WHERE source_id = ? OR target_id = ?",
            (citation_id, citation_id),
        )
        return [dict(row) for row in rows]

    async def citation_subgraph(
        self, seed_ids: list[str], max_depth: int = 2
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """BFS over citation_relationships from seed paper IDs up to max_depth.

        Returns (nodes, edges) as plain dict lists — the litmaps-style export shape.
        """
        visited: set[str] = set()
        frontier: set[str] = set(seed_ids or [])
        edges_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}

        depth = 0
        while frontier and depth <= max_depth:
            next_frontier: set[str] = set()
            for citation_id in frontier:
                if citation_id in visited:
                    continue
                visited.add(citation_id)

                for edge in await self.get_citation_edges(citation_id):
                    key = (edge["source_id"], edge["target_id"], edge["relationship_type"])
                    edges_by_key[key] = edge
                    for neighbor in (edge["source_id"], edge["target_id"]):
                        if neighbor not in visited:
                            next_frontier.add(neighbor)

            frontier = next_frontier
            depth += 1

        nodes = []
        for citation_id in visited:
            node = await self.get_citation(citation_id)
            if node:
                nodes.append(node)

        return nodes, list(edges_by_key.values())

    # ========== LINKING METHODS ==========

    async def link_interest_to_concept(
        self, interest_id: str, concept_id: str, link_type: str = "related", confidence: float = 0.8
    ) -> None:
        """Create a link between an interest and a concept."""
        now = utcnow().isoformat()
        
        await self._db.execute("""
            INSERT INTO interest_concept_links (interest_id, concept_id, link_type, confidence, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(interest_id, concept_id) DO UPDATE SET
                link_type = excluded.link_type,
                confidence = excluded.confidence
        """, (interest_id, concept_id, link_type, confidence, now))
        await self._db.commit()

    async def get_linked_concepts_for_interest(self, interest_id: str) -> list[dict[str, Any]]:
        """Get all concepts linked to an interest."""
        rows = await self._db.fetchall("""
            SELECT c.*, icl.link_type, icl.confidence
            FROM concepts c
            JOIN interest_concept_links icl ON c.id = icl.concept_id
            WHERE icl.interest_id = ?
            ORDER BY icl.confidence DESC
        """, (interest_id,))
        return [dict(row) for row in rows]

    async def get_linked_interests_for_concept(self, concept_id: str) -> list[dict[str, Any]]:
        """Get all interests linked to a concept."""
        rows = await self._db.fetchall("""
            SELECT i.*, icl.link_type, icl.confidence
            FROM interests i
            JOIN interest_concept_links icl ON i.id = icl.interest_id
            WHERE icl.concept_id = ?
            ORDER BY i.strength DESC
        """, (concept_id,))
        return [dict(row) for row in rows]

    async def link_citation_to_concept(
        self, citation_id: str, concept_id: str, relation_type: str = "discusses", evidence_text: str = None
    ) -> None:
        """Create a link between a citation and a concept."""
        now = utcnow().isoformat()
        
        await self._db.execute("""
            INSERT INTO citation_concept_links (citation_id, concept_id, relation_type, evidence_text, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(citation_id, concept_id) DO UPDATE SET
                relation_type = excluded.relation_type,
                evidence_text = excluded.evidence_text
        """, (citation_id, concept_id, relation_type, evidence_text, now))
        await self._db.commit()

    async def get_linked_concepts_for_citation(self, citation_id: str) -> list[dict[str, Any]]:
        """Get all concepts linked to a citation."""
        rows = await self._db.fetchall("""
            SELECT c.*, ccl.relation_type, ccl.evidence_text
            FROM concepts c
            JOIN citation_concept_links ccl ON c.id = ccl.concept_id
            WHERE ccl.citation_id = ?
        """, (citation_id,))
        return [dict(row) for row in rows]

    async def get_linked_citations_for_concept(self, concept_id: str) -> list[dict[str, Any]]:
        """Get all citations linked to a concept."""
        rows = await self._db.fetchall("""
            SELECT ci.*, ccl.relation_type, ccl.evidence_text
            FROM citations ci
            JOIN citation_concept_links ccl ON ci.id = ccl.citation_id
            WHERE ccl.concept_id = ?
            ORDER BY ci.published_date DESC
        """, (concept_id,))
        return [dict(row) for row in rows]

    async def link_interest_to_citation(
        self,
        interest_id: str,
        citation_id: str,
        relevance: float = 0.5,
        discovered_run_id: Optional[str] = None,
    ) -> None:
        """Create a link between an interest and a citation (G6: research → interest)."""
        now = utcnow().isoformat()

        await self._db.execute("""
            INSERT INTO interest_citation_links (interest_id, citation_id, relevance, discovered_run_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(interest_id, citation_id) DO UPDATE SET
                relevance = excluded.relevance
        """, (interest_id, citation_id, relevance, discovered_run_id, now))
        await self._db.commit()

    async def get_citations_for_interest(self, interest_id: str) -> list[dict[str, Any]]:
        """Get all citations linked to an interest, most relevant first."""
        rows = await self._db.fetchall("""
            SELECT c.*, icl.relevance, icl.discovered_run_id
            FROM citations c
            JOIN interest_citation_links icl ON c.id = icl.citation_id
            WHERE icl.interest_id = ?
            ORDER BY icl.relevance DESC
        """, (interest_id,))
        return [dict(row) for row in rows]

    async def get_existing_research(
        self, topic: str, interest_id: Optional[str] = None
    ) -> dict[str, Any]:
        """What we already know about a topic, for reuse (G6) — prior runs, papers, concepts.

        When `interest_id` is given, looks through the precise interest link tables;
        otherwise falls back to a title/label match on `topic`.
        """
        runs = await self.get_research_runs(topic=topic, interest_id=interest_id)
        if interest_id:
            citations = await self.get_citations_for_interest(interest_id)
            concepts = await self.get_linked_concepts_for_interest(interest_id)
        else:
            citations = await self.find_citations_by_title(topic)
            concepts = await self.find_concepts_by_label(topic)
        return {"runs": runs, "citations": citations, "concepts": concepts}

    # ========== RESEARCH RUN PROVENANCE METHODS ==========

    async def start_research_run(self, run: dict[str, Any]) -> str:
        """Record the start of a research run. Returns the run_id."""
        import uuid

        run_id = run.get("id") or uuid.uuid4().hex
        now = utcnow().isoformat()

        await self._db.execute("""
            INSERT INTO research_runs (id, topic, interest_id, trigger_source, depth, status, started_at)
            VALUES (?, ?, ?, ?, ?, 'running', ?)
        """, (
            run_id,
            run["topic"],
            run.get("interest_id"),
            run.get("trigger_source", "manual"),
            run.get("depth", "normal"),
            now,
        ))
        await self._db.commit()
        return run_id

    async def finish_research_run(self, run_id: str, *, status: str = "completed", **fields: Any) -> None:
        """Mark a research run finished, recording its deltas/summary/error."""
        allowed = {
            "papers_found", "papers_new", "concepts_extracted", "concepts_new",
            "relationships_found", "summary", "error",
        }
        set_clauses = ["status = ?", "completed_at = ?"]
        params: list[Any] = [status, utcnow().isoformat()]
        for key, value in fields.items():
            if key in allowed:
                set_clauses.append(f"{key} = ?")
                params.append(value)
        params.append(run_id)

        await self._db.execute(
            f"UPDATE research_runs SET {', '.join(set_clauses)} WHERE id = ?", params
        )
        await self._db.commit()

    async def get_research_runs(
        self, topic: Optional[str] = None, interest_id: Optional[str] = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """List research runs, most recent first, optionally filtered by topic/interest."""
        conditions = []
        params: list[Any] = []
        if topic:
            conditions.append("topic = ?")
            params.append(topic)
        if interest_id:
            conditions.append("interest_id = ?")
            params.append(interest_id)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        rows = await self._db.fetchall(
            f"SELECT * FROM research_runs {where} ORDER BY started_at DESC LIMIT ?", params
        )
        return [dict(row) for row in rows]

    # ========== UTILITY METHODS ==========

    async def get_stats(self) -> dict[str, int]:
        """Get counts of all entities."""
        tables = [
            "interests", "concepts", "citations",
            "interest_concept_links", "citation_concept_links",
            "citation_relationships", "concept_relationships",
            "interest_citation_links", "research_runs",
        ]
        stats = {}
        
        for table in tables:
            row = await self._db.fetchone(f"SELECT COUNT(*) as count FROM {table}")
            stats[table] = row["count"]
        
        return stats

    async def execute_query(self, query: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Execute a custom query and return results."""
        rows = await self._db.fetchall(query, params)
        return [dict(row) for row in rows]

    # ========== INTEREST SIGNAL EVIDENCE METHODS ==========

    async def add_classified_signal(
        self,
        signal_id: str,
        topic: str,
        confidence: float,
        timestamp: str,
    ) -> None:
        """Add a classified signal as evidence for a topic's interest strength."""
        now = utcnow().isoformat()

        await self._db.execute("""
            INSERT INTO interest_signal_evidence (signal_id, topic, confidence, timestamp)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(signal_id, topic) DO UPDATE SET 
                confidence = excluded.confidence, 
                timestamp = excluded.timestamp
        """, (signal_id, topic, confidence, timestamp))

        await self._db.execute("""
            INSERT INTO interests (id, label, strength, created_at, updated_at, last_active)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET 
                last_active = excluded.last_active
        """, (topic, topic, confidence, now, now, now))

        await self._db.commit()

    async def get_strength(self, topic: str, decay_hours: int = 720) -> float:
        """Compute interest strength as a decayed sum of signal evidence."""
        import math
        
        rows = await self._db.fetchall(
            "SELECT confidence, timestamp FROM interest_signal_evidence WHERE topic = ?",
            (topic,),
        )

        if not rows:
            return 0.0

        now = utcnow()
        total = 0.0
        for row in rows:
            age_hours = (now - datetime.fromisoformat(row["timestamp"])).total_seconds() / 3600
            total += row["confidence"] * math.exp(-age_hours / decay_hours)

        return max(0.0, min(1.0, total))

    async def should_research(self, topic: str, cooldown_hours: int = 24) -> bool:
        """Check if enough time has passed since last research on this topic."""
        row = await self._db.fetchone(
            "SELECT last_researched_at FROM interest_research_log WHERE topic = ?",
            (topic,),
        )
        
        if not row:
            return True

        last_researched = datetime.fromisoformat(row["last_researched_at"])
        age_hours = (utcnow() - last_researched).total_seconds() / 3600

        return age_hours >= cooldown_hours

    async def mark_researched(self, topic: str) -> None:
        """Mark a topic as researched now, starting its cooldown window."""
        now = utcnow().isoformat()

        await self._db.execute("""
            INSERT INTO interest_research_log (topic, last_researched_at)
            VALUES (?, ?)
            ON CONFLICT(topic) DO UPDATE SET last_researched_at = ?
        """, (topic, now, now))
        await self._db.commit()

    @staticmethod
    def cosine_similarity(a: list[float], b: bytes) -> float:
        """Compute cosine similarity between two vectors.
        
        Args:
            a: List of floats (query embedding)
            b: Bytes (stored embedding from database)
            
        Returns:
            Cosine similarity score (0.0 to 1.0)
        """
        import struct
        import math
        
        # Unpack bytes to float list (assuming float32)
        vector_size = len(b) // 4  # 4 bytes per float32
        b_list = list(struct.unpack(f'{vector_size}f', b))
        
        # Compute dot product
        dot_product = sum(x * y for x, y in zip(a, b_list))
        
        # Compute magnitudes
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(x * x for x in b_list))
        
        if mag_a == 0 or mag_b == 0:
            return 0.0
        
        return dot_product / (mag_a * mag_b)

    # ========== CONVERSATION SESSION METHODS ==========

    async def create_conversation_session(
        self, 
        session_id: str, 
        user_id: str = "cli",
        metadata: dict[str, Any] = None
    ) -> None:
        """Create a new conversation session."""
        now = utcnow().isoformat()
        await self._db.execute("""
            INSERT INTO conversation_sessions (id, user_id, created_at, updated_at, question_count, metadata)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (session_id, user_id, now, now, 0, json.dumps(metadata) if metadata else None))
        await self._db.commit()

    async def get_or_create_session(
        self, 
        session_id: str, 
        user_id: str = "cli"
    ) -> str:
        """Get existing session or create new one. Returns session_id."""
        row = await self._db.fetchone(
            "SELECT id FROM conversation_sessions WHERE id = ?",
            (session_id,)
        )
        if not row:
            await self.create_conversation_session(session_id, user_id)
        return session_id

    async def add_conversation_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] = None
    ) -> int:
        """Add a turn to a conversation session."""
        now = utcnow().isoformat()
        
        row = await self._db.fetchone(
            "SELECT MAX(turn_number) as max_turn FROM conversation_turns WHERE session_id = ?",
            (session_id,)
        )
        turn_number = (row["max_turn"] or 0) + 1
        
        await self._db.execute("""
            INSERT INTO conversation_turns (session_id, turn_number, role, content, timestamp, metadata)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (session_id, turn_number, role, content, now, json.dumps(metadata) if metadata else None))
        
        await self._db.execute("""
            UPDATE conversation_sessions 
            SET question_count = question_count + 1, updated_at = ?
            WHERE id = ?
        """, (now, session_id))
        
        await self._db.commit()
        return turn_number

    async def get_conversation_history(
        self,
        session_id: str,
        limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get conversation history for a session."""
        rows = await self._db.fetchall("""
            SELECT * FROM conversation_turns
            WHERE session_id = ?
            ORDER BY turn_number DESC
            LIMIT ?
        """, (session_id, limit))
        return [dict(row) for row in reversed(rows)]

    async def get_session_info(self, session_id: str) -> Optional[dict[str, Any]]:
        """Get session metadata."""
        row = await self._db.fetchone(
            "SELECT * FROM conversation_sessions WHERE id = ?",
            (session_id,)
        )
        return dict(row) if row else None

    async def clear_conversation_history(self, session_id: str) -> None:
        """Clear all turns from a session."""
        await self._db.execute(
            "DELETE FROM conversation_turns WHERE session_id = ?",
            (session_id,)
        )
        await self._db.execute(
            "UPDATE conversation_sessions SET question_count = 0, updated_at = ? WHERE id = ?",
            (utcnow().isoformat(), session_id)
        )
        await self._db.commit()

    # ========== USER STATISTICS METHODS ==========

    async def increment_user_question_count(self, user_id: str) -> int:
        """Increment user's question count and return new total."""
        now = utcnow().isoformat()
        
        await self._db.execute("""
            INSERT INTO user_stats (user_id, total_questions, last_active, updated_at)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                total_questions = total_questions + 1,
                last_active = excluded.last_active,
                updated_at = excluded.updated_at
        """, (user_id, now, now))
        
        row = await self._db.fetchone(
            "SELECT total_questions FROM user_stats WHERE user_id = ?",
            (user_id,)
        )
        await self._db.commit()
        return row["total_questions"]

    async def get_user_stats(self, user_id: str) -> Optional[dict[str, Any]]:
        """Get statistics for a user."""
        row = await self._db.fetchone(
            "SELECT * FROM user_stats WHERE user_id = ?",
            (user_id,)
        )
        return dict(row) if row else None

    async def increment_knowledge_entries(self, user_id: str) -> None:
        """Increment user's knowledge entry count."""
        now = utcnow().isoformat()
        await self._db.execute("""
            INSERT INTO user_stats (user_id, total_knowledge_entries, updated_at)
            VALUES (?, 1, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                total_knowledge_entries = total_knowledge_entries + 1,
                updated_at = excluded.updated_at
        """, (user_id, now))
        await self._db.commit()

    # ========== KNOWLEDGE ENTRY METHODS ==========

    async def store_knowledge_entry(
        self,
        entry_id: str,
        question: str,
        answer: str,
        quality_score: float,
        user_id: str,
        session_id: str = None,
        metadata: dict[str, Any] = None
    ) -> None:
        """Store a high-quality Q&A pair as a knowledge entry."""
        now = utcnow().isoformat()
        
        await self._db.execute("""
            INSERT INTO knowledge_entries (id, question, answer, quality_score, source_session_id, user_id, created_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (entry_id, question, answer, quality_score, session_id, user_id, now, json.dumps(metadata) if metadata else None))
        
        await self.increment_knowledge_entries(user_id)
        await self._db.commit()

    async def get_knowledge_entries(
        self,
        user_id: str = None,
        min_quality: float = 0.0,
        limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get knowledge entries filtered by user and quality."""
        if user_id:
            rows = await self._db.fetchall("""
                SELECT * FROM knowledge_entries
                WHERE user_id = ? AND quality_score >= ?
                ORDER BY quality_score DESC, created_at DESC
                LIMIT ?
            """, (user_id, min_quality, limit))
        else:
            rows = await self._db.fetchall("""
                SELECT * FROM knowledge_entries
                WHERE quality_score >= ?
                ORDER BY quality_score DESC, created_at DESC
                LIMIT ?
            """, (min_quality, limit))
        return [dict(row) for row in rows]

    async def search_knowledge_entries(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search knowledge entries by question/answer content."""
        rows = await self._db.fetchall("""
            SELECT * FROM knowledge_entries
            WHERE question LIKE ? OR answer LIKE ?
            ORDER BY quality_score DESC
            LIMIT ?
        """, (f"%{query}%", f"%{query}%", limit))
        return [dict(row) for row in rows]
