"""Unified knowledge store - merges memory, citations, and concept graphs into single SQLite database."""

import aiosqlite
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def utcnow() -> datetime:
    """Get current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)

logger = logging.getLogger(__name__)


class UnifiedKnowledgeStore:
    """
    Unified SQLite knowledge store that consolidates:
    - User memory (interests, profile, opportunities)
    - Citation graph (research papers)
    - Knowledge graph (concepts and relationships)
    
    All cross-references are maintained via linking tables.
    """

    def __init__(self, db_path: str = "./data/knowledge.db"):
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def initialize(self) -> None:
        """Initialize database connection and create tables."""
        logger.info(f"Initializing unified knowledge store: {self.db_path}")
        
        # Ensure directory exists
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        
        # Enable foreign keys
        await self._db.execute("PRAGMA foreign_keys = ON")
        
        # Create all tables
        await self._create_tables()
        
        logger.info("Unified knowledge store initialized successfully")

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
        
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS citation_relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relationship_type TEXT,
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
        cursor = await self._db.execute(
            "SELECT * FROM interests WHERE id = ?",
            (interest_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_interests(self, min_strength: float = 0.0) -> list[dict[str, Any]]:
        """Get all interests above minimum strength threshold."""
        cursor = await self._db.execute(
            "SELECT * FROM interests WHERE strength >= ? ORDER BY strength DESC",
            (min_strength,),
        )
        rows = await cursor.fetchall()
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
        cursor = await self._db.execute(
            "SELECT embedding FROM interest_embeddings WHERE interest_id = ?",
            (interest_id,),
        )
        row = await cursor.fetchone()
        return row["embedding"] if row else None

    async def get_all_interest_embeddings(self) -> list[tuple[str, bytes]]:
        """Get all cached interest embeddings with their IDs."""
        cursor = await self._db.execute(
            "SELECT ie.interest_id, ie.embedding, i.label "
            "FROM interest_embeddings ie "
            "JOIN interests i ON ie.interest_id = i.id"
        )
        rows = await cursor.fetchall()
        return [(row["interest_id"], row["embedding"], row["label"]) for row in rows]

    async def get_interest_embeddings(self, min_strength: float = 0.2) -> list[tuple[str, bytes, str]]:
        """Get embeddings for interests above minimum strength threshold.
        
        Returns list of (interest_id, embedding_bytes, label) tuples.
        """
        cursor = await self._db.execute("""
            SELECT ie.interest_id, ie.embedding, i.label
            FROM interest_embeddings ie
            JOIN interests i ON ie.interest_id = i.id
            WHERE i.strength >= ?
            ORDER BY i.strength DESC
        """, (min_strength,))
        rows = await cursor.fetchall()
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
        cursor = await self._db.execute(
            "SELECT * FROM concepts WHERE id = ?",
            (concept_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_all_concepts(self) -> list[dict[str, Any]]:
        """Get all concepts."""
        cursor = await self._db.execute("SELECT * FROM concepts ORDER BY label")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def find_concepts_by_label(self, label_pattern: str) -> list[dict[str, Any]]:
        """Find concepts matching label pattern (SQL LIKE)."""
        cursor = await self._db.execute(
            "SELECT * FROM concepts WHERE label LIKE ? OR label = ?",
            (f"%{label_pattern}%", label_pattern),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # ========== CITATION METHODS ==========

    async def upsert_citation(self, citation: dict[str, Any]) -> None:
        """Insert or update a citation."""
        now = utcnow().isoformat()
        
        await self._db.execute("""
            INSERT INTO citations (id, arxiv_id, doi, title, abstract, authors, 
                                   published_date, journal, categories, citation_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                abstract = excluded.abstract,
                authors = excluded.authors,
                published_date = excluded.published_date,
                journal = excluded.journal,
                categories = excluded.categories,
                citation_count = excluded.citation_count
        """, (
            citation.get("id"),
            citation.get("arxiv_id"),
            citation.get("doi"),
            citation.get("title"),
            citation.get("abstract"),
            citation.get("authors"),  # JSON string
            citation.get("published_date"),
            citation.get("journal"),
            citation.get("categories"),  # JSON string
            citation.get("citation_count", 0),
            now,
        ))
        await self._db.commit()

    async def get_citation(self, citation_id: str) -> Optional[dict[str, Any]]:
        """Get a citation by ID."""
        cursor = await self._db.execute(
            "SELECT * FROM citations WHERE id = ?",
            (citation_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_all_citations(self) -> list[dict[str, Any]]:
        """Get all citations."""
        cursor = await self._db.execute("SELECT * FROM citations ORDER BY published_date DESC")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

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
        cursor = await self._db.execute("""
            SELECT c.*, icl.link_type, icl.confidence
            FROM concepts c
            JOIN interest_concept_links icl ON c.id = icl.concept_id
            WHERE icl.interest_id = ?
            ORDER BY icl.confidence DESC
        """, (interest_id,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_linked_interests_for_concept(self, concept_id: str) -> list[dict[str, Any]]:
        """Get all interests linked to a concept."""
        cursor = await self._db.execute("""
            SELECT i.*, icl.link_type, icl.confidence
            FROM interests i
            JOIN interest_concept_links icl ON i.id = icl.interest_id
            WHERE icl.concept_id = ?
            ORDER BY i.strength DESC
        """, (concept_id,))
        rows = await cursor.fetchall()
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
        cursor = await self._db.execute("""
            SELECT c.*, ccl.relation_type, ccl.evidence_text
            FROM concepts c
            JOIN citation_concept_links ccl ON c.id = ccl.concept_id
            WHERE ccl.citation_id = ?
        """, (citation_id,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_linked_citations_for_concept(self, concept_id: str) -> list[dict[str, Any]]:
        """Get all citations linked to a concept."""
        cursor = await self._db.execute("""
            SELECT ci.*, ccl.relation_type, ccl.evidence_text
            FROM citations ci
            JOIN citation_concept_links ccl ON ci.id = ccl.citation_id
            WHERE ccl.concept_id = ?
            ORDER BY ci.published_date DESC
        """, (concept_id,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # ========== UTILITY METHODS ==========

    async def get_stats(self) -> dict[str, int]:
        """Get counts of all entities."""
        tables = ["interests", "concepts", "citations", 
                  "interest_concept_links", "citation_concept_links"]
        stats = {}
        
        for table in tables:
            cursor = await self._db.execute(f"SELECT COUNT(*) as count FROM {table}")
            row = await cursor.fetchone()
            stats[table] = row["count"]
        
        return stats

    async def execute_query(self, query: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Execute a custom query and return results."""
        cursor = await self._db.execute(query, params)
        rows = await cursor.fetchall()
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
        
        cursor = await self._db.execute(
            "SELECT confidence, timestamp FROM interest_signal_evidence WHERE topic = ?",
            (topic,),
        )
        rows = await cursor.fetchall()

        if not rows:
            return 0.0

        now = utcnow()
        total = 0.0
        for confidence, ts_str in rows:
            age_hours = (now - datetime.fromisoformat(ts_str)).total_seconds() / 3600
            total += confidence * math.exp(-age_hours / decay_hours)

        return max(0.0, min(1.0, total))

    async def should_research(self, topic: str, cooldown_hours: int = 24) -> bool:
        """Check if enough time has passed since last research on this topic."""
        cursor = await self._db.execute(
            "SELECT last_researched_at FROM interest_research_log WHERE topic = ?",
            (topic,),
        )
        row = await cursor.fetchone()
        
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
        cursor = await self._db.execute(
            "SELECT id FROM conversation_sessions WHERE id = ?",
            (session_id,)
        )
        row = await cursor.fetchone()
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
        
        cursor = await self._db.execute(
            "SELECT MAX(turn_number) as max_turn FROM conversation_turns WHERE session_id = ?",
            (session_id,)
        )
        row = await cursor.fetchone()
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
        cursor = await self._db.execute("""
            SELECT * FROM conversation_turns 
            WHERE session_id = ? 
            ORDER BY turn_number DESC 
            LIMIT ?
        """, (session_id, limit))
        rows = await cursor.fetchall()
        return [dict(row) for row in reversed(rows)]

    async def get_session_info(self, session_id: str) -> Optional[dict[str, Any]]:
        """Get session metadata."""
        cursor = await self._db.execute(
            "SELECT * FROM conversation_sessions WHERE id = ?",
            (session_id,)
        )
        row = await cursor.fetchone()
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
        
        cursor = await self._db.execute(
            "SELECT total_questions FROM user_stats WHERE user_id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()
        await self._db.commit()
        return row["total_questions"]

    async def get_user_stats(self, user_id: str) -> Optional[dict[str, Any]]:
        """Get statistics for a user."""
        cursor = await self._db.execute(
            "SELECT * FROM user_stats WHERE user_id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()
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
            cursor = await self._db.execute("""
                SELECT * FROM knowledge_entries 
                WHERE user_id = ? AND quality_score >= ?
                ORDER BY quality_score DESC, created_at DESC
                LIMIT ?
            """, (user_id, min_quality, limit))
        else:
            cursor = await self._db.execute("""
                SELECT * FROM knowledge_entries 
                WHERE quality_score >= ?
                ORDER BY quality_score DESC, created_at DESC
                LIMIT ?
            """, (min_quality, limit))
        
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def search_knowledge_entries(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search knowledge entries by question/answer content."""
        cursor = await self._db.execute("""
            SELECT * FROM knowledge_entries 
            WHERE question LIKE ? OR answer LIKE ?
            ORDER BY quality_score DESC
            LIMIT ?
        """, (f"%{query}%", f"%{query}%", limit))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
