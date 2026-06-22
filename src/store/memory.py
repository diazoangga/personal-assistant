"""User Memory - SQLite storage for profile, interests, opportunities, and feedback."""

import asyncio
import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import aiosqlite
from aiosqlite import Connection

logger = logging.getLogger(__name__)


@dataclass
class InterestNode:
    """An interest node in the user's interest graph."""

    id: str
    label: str
    strength: float  # 0.0 to 1.0
    last_active: str  # ISO date
    decay_rate: float = 0.01  # Daily decay

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "strength": self.strength,
            "last_active": self.last_active,
            "decay_rate": self.decay_rate,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InterestNode":
        return cls(
            id=data["id"],
            label=data["label"],
            strength=data["strength"],
            last_active=data["last_active"],
            decay_rate=data.get("decay_rate", 0.01),
        )


@dataclass
class InterestEdge:
    """An edge between interest nodes."""

    source_id: str
    target_id: str
    weight: float  # 0.0 to 1.0
    relation_type: str  # "related_to", "parent_of", "child_of"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "weight": self.weight,
            "relation_type": self.relation_type,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InterestEdge":
        return cls(
            source_id=data["source_id"],
            target_id=data["target_id"],
            weight=data["weight"],
            relation_type=data["relation_type"],
        )


@dataclass
class Opportunity:
    """A career/learning opportunity."""

    id: str
    title: str
    description: str
    source_url: str | None
    relevance_score: float  # 0.0 to 1.0
    matched_interests: list[str]  # List of interest IDs
    created_at: str  # ISO date
    status: str = "new"  # "new", "reviewed", "saved", "dismissed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "source_url": self.source_url,
            "relevance_score": self.relevance_score,
            "matched_interests": json.dumps(self.matched_interests),
            "created_at": self.created_at,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Opportunity":
        matched = data.get("matched_interests", "[]")
        if isinstance(matched, str):
            matched = json.loads(matched)
        return cls(
            id=data["id"],
            title=data["title"],
            description=data["description"],
            source_url=data.get("source_url"),
            relevance_score=data["relevance_score"],
            matched_interests=matched,
            created_at=data["created_at"],
            status=data.get("status", "new"),
        )


@dataclass
class Feedback:
    """User feedback on assistant outputs."""

    id: str
    job_id: str
    feedback_type: str  # "thumbs_up", "thumbs_down", "correction"
    comment: str | None
    created_at: str  # ISO date

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "job_id": self.job_id,
            "feedback_type": self.feedback_type,
            "comment": self.comment,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Feedback":
        return cls(
            id=data["id"],
            job_id=data["job_id"],
            feedback_type=data["feedback_type"],
            comment=data.get("comment"),
            created_at=data["created_at"],
        )


@dataclass
class Proposal:
    """A self-modification proposal (D6)."""

    id: str
    proposal_type: str  # "new_skill", "modify_skill", "new_topic", "modify_topic"
    description: str
    rationale: str
    code_diff: str | None
    status: str = "pending"  # "pending", "approved", "rejected"
    created_at: str | None = None
    reviewed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "proposal_type": self.proposal_type,
            "description": self.description,
            "rationale": self.rationale,
            "code_diff": self.code_diff,
            "status": self.status,
            "created_at": self.created_at,
            "reviewed_at": self.reviewed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Proposal":
        return cls(
            id=data["id"],
            proposal_type=data["proposal_type"],
            description=data["description"],
            rationale=data["rationale"],
            code_diff=data.get("code_diff"),
            status=data.get("status", "pending"),
            created_at=data.get("created_at"),
            reviewed_at=data.get("reviewed_at"),
        )


class UserMemory:
    """
    SQLite-based user memory store.

    Stores:
    - User profile (key/value)
    - Interest graph (nodes and edges)
    - Opportunities
    - Feedback
    - Jobs/sessions
    - Proposals (for D6 self-modification)
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._db: Connection | None = None

    async def initialize(self) -> None:
        """Initialize the database schema."""
        logger.debug(f"Initializing UserMemory database at {self.db_path}")
        self._db = await aiosqlite.connect(self.db_path)
        await self._create_tables()
        logger.info("UserMemory database initialized successfully")

    async def _create_tables(self) -> None:
        """Create all tables."""
        assert self._db is not None

        # User profile
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS profile (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Interest graph
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS interest_nodes (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                strength REAL NOT NULL,
                last_active TEXT NOT NULL,
                decay_rate REAL DEFAULT 0.01
            )
        """)

        # Per-signal evidence backing each interest's strength (decayed sum)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS interest_signal_evidence (
                signal_id TEXT NOT NULL,
                topic TEXT NOT NULL,
                confidence REAL NOT NULL,
                timestamp TEXT NOT NULL,
                PRIMARY KEY (signal_id, topic)
            )
        """)

        # Tracks when a topic was last sent to the Research Agent (cooldown)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS interest_research_log (
                topic TEXT PRIMARY KEY,
                last_researched_at TEXT NOT NULL
            )
        """)

        # Embedding cache for interest labels (hybrid classification)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS interest_embeddings (
                interest_id TEXT PRIMARY KEY,
                embedding BLOB NOT NULL,
                model_version TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (interest_id) REFERENCES interest_nodes(id)
            )
        """)

        # Link interests to concept nodes (unified knowledge graph)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS interest_concept_links (
                interest_id TEXT NOT NULL,
                concept_id TEXT NOT NULL,
                link_type TEXT NOT NULL,
                confidence REAL NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (interest_id, concept_id),
                FOREIGN KEY (interest_id) REFERENCES interest_nodes(id),
                FOREIGN KEY (concept_id) REFERENCES concept_nodes(id)
            )
        """)

        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS interest_edges (
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                weight REAL NOT NULL,
                relation_type TEXT NOT NULL,
                PRIMARY KEY (source_id, target_id),
                FOREIGN KEY (source_id) REFERENCES interest_nodes(id),
                FOREIGN KEY (target_id) REFERENCES interest_nodes(id)
            )
        """)

        # Opportunities
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS opportunities (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                source_url TEXT,
                relevance_score REAL NOT NULL,
                matched_interests TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT DEFAULT 'new'
            )
        """)

        # Feedback
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                feedback_type TEXT NOT NULL,
                comment TEXT,
                created_at TEXT NOT NULL
            )
        """)

        # Jobs/sessions
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                command_type TEXT NOT NULL,
                status TEXT NOT NULL,
                context TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT
            )
        """)

        # Proposals (D6)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS proposals (
                id TEXT PRIMARY KEY,
                proposal_type TEXT NOT NULL,
                description TEXT NOT NULL,
                rationale TEXT NOT NULL,
                code_diff TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                reviewed_at TEXT
            )
        """)

        await self._db.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            logger.debug("Closing UserMemory database connection")
            await self._db.close()
            logger.info("UserMemory database connection closed")

    # Profile operations

    async def set_profile(self, key: str, value: Any) -> None:
        """Set a profile value."""
        assert self._db is not None
        now = datetime.utcnow().isoformat()
        await self._db.execute(
            """
            INSERT INTO profile (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?
            """,
            (key, json.dumps(value), now, json.dumps(value), now),
        )
        await self._db.commit()

    async def get_profile(self, key: str) -> Any | None:
        """Get a profile value."""
        assert self._db is not None
        async with self._db.execute(
            "SELECT value FROM profile WHERE key = ?", (key,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return json.loads(row[0])
            return None

    async def get_all_profile(self) -> dict[str, Any]:
        """Get all profile values."""
        assert self._db is not None
        profile = {}
        async with self._db.execute("SELECT key, value FROM profile") as cursor:
            async for key, value in cursor:
                profile[key] = json.loads(value)
        return profile

    # Interest graph operations

    async def upsert_interest(self, node: InterestNode) -> None:
        """Upsert an interest node."""
        assert self._db is not None
        await self._db.execute(
            """
            INSERT INTO interest_nodes (id, label, strength, last_active, decay_rate)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                strength = ?,
                last_active = ?,
                decay_rate = ?
            """,
            (
                node.id,
                node.label,
                node.strength,
                node.last_active,
                node.decay_rate,
                node.strength,
                node.last_active,
                node.decay_rate,
            ),
        )
        await self._db.commit()

    async def add_interest_edge(self, edge: InterestEdge) -> None:
        """Add or update an interest edge."""
        assert self._db is not None
        await self._db.execute(
            """
            INSERT INTO interest_edges (source_id, target_id, weight, relation_type)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source_id, target_id) DO UPDATE SET
                weight = ?,
                relation_type = ?
            """,
            (
                edge.source_id,
                edge.target_id,
                edge.weight,
                edge.relation_type,
                edge.weight,
                edge.relation_type,
            ),
        )
        await self._db.commit()

    async def get_interests(self, min_strength: float = 0.0) -> list[InterestNode]:
        """Get all interests above a strength threshold."""
        assert self._db is not None
        nodes = []
        async with self._db.execute(
            "SELECT * FROM interest_nodes WHERE strength >= ?", (min_strength,)
        ) as cursor:
            async for row in cursor:
                nodes.append(
                    InterestNode(
                        id=row[0],
                        label=row[1],
                        strength=row[2],
                        last_active=row[3],
                        decay_rate=row[4],
                    )
                )
        return nodes

    async def decay_interests(self, days: int = 1) -> None:
        """Apply decay to all interests based on inactivity."""
        assert self._db is not None
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        await self._db.execute(
            """
            UPDATE interest_nodes
            SET strength = MAX(0, strength - decay_rate * ?)
            WHERE last_active < ?
            """,
            (days, cutoff),
        )
        await self._db.commit()

    async def get_related_interests(self, interest_id: str) -> list[InterestNode]:
        """Get interests related to a given interest."""
        assert self._db is not None
        query = """
            SELECT n.* FROM interest_nodes n
            JOIN interest_edges e ON n.id = e.target_id
            WHERE e.source_id = ?
        """
        nodes = []
        async with self._db.execute(query, (interest_id,)) as cursor:
            async for row in cursor:
                nodes.append(
                    InterestNode(
                        id=row[0],
                        label=row[1],
                        strength=row[2],
                        last_active=row[3],
                        decay_rate=row[4],
                    )
                )
        return nodes

    async def add_classified_signal(
        self,
        user_id: str,
        signal_id: str,
        topic: str,
        confidence: float,
        timestamp: datetime,
    ) -> None:
        """Add a classified signal as evidence for a topic's interest strength."""
        assert self._db is not None
        now = datetime.utcnow().isoformat()
        ts = timestamp.isoformat()

        # Record the evidence (drives decayed strength calculation)
        await self._db.execute(
            """
            INSERT INTO interest_signal_evidence (signal_id, topic, confidence, timestamp)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(signal_id, topic) DO UPDATE SET confidence = ?, timestamp = ?
            """,
            (signal_id, topic, confidence, ts, confidence, ts),
        )

        # Upsert the interest node for label/last_active bookkeeping
        await self._db.execute(
            """
            INSERT INTO interest_nodes (id, label, strength, last_active, decay_rate)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET last_active = ?
            """,
            (topic, topic, confidence, now, 0.01, now),
        )

        await self._db.commit()

    async def get_strength(
        self, user_id: str, topic: str, decay_hours: int = 720
    ) -> float:
        """
        Compute interest strength as a decayed sum of signal evidence.
        Recent signals contribute more than old ones; clipped to [0, 1].
        """
        assert self._db is not None

        async with self._db.execute(
            "SELECT confidence, timestamp FROM interest_signal_evidence WHERE topic = ?",
            (topic,),
        ) as cursor:
            rows = await cursor.fetchall()

        if not rows:
            return 0.0

        now = datetime.utcnow()
        total = 0.0
        for confidence, ts_str in rows:
            age_hours = (now - datetime.fromisoformat(ts_str)).total_seconds() / 3600
            total += confidence * math.exp(-age_hours / decay_hours)

        return max(0.0, min(1.0, total))

    async def get_strengthened_topics(
        self, user_id: str, threshold_increase: float = 0.1, window_hours: int = 6
    ) -> list[tuple[str, float, float]]:
        """
        Get topics whose strength increased since it was last cached.
        Returns: [(topic, old_strength, new_strength), ...]
        """
        assert self._db is not None

        topics_changed = []
        async with self._db.execute(
            "SELECT id, strength FROM interest_nodes ORDER BY last_active DESC"
        ) as cursor:
            rows = await cursor.fetchall()

        for topic, old_strength in rows:
            new_strength = await self.get_strength(user_id, topic)
            delta = new_strength - old_strength
            if delta >= threshold_increase:
                topics_changed.append((topic, old_strength, new_strength))
                await self._db.execute(
                    "UPDATE interest_nodes SET strength = ? WHERE id = ?",
                    (new_strength, topic),
                )

        await self._db.commit()
        return sorted(topics_changed, key=lambda x: x[2] - x[1], reverse=True)

    async def mark_researched(self, user_id: str, topic: str) -> None:
        """Mark a topic as researched now, starting its cooldown window."""
        assert self._db is not None
        now = datetime.utcnow().isoformat()

        await self._db.execute(
            """
            INSERT INTO interest_research_log (topic, last_researched_at)
            VALUES (?, ?)
            ON CONFLICT(topic) DO UPDATE SET last_researched_at = ?
            """,
            (topic, now, now),
        )
        await self._db.commit()

    async def should_research(
        self, user_id: str, topic: str, cooldown_hours: int = 24
    ) -> bool:
        """Check if enough time has passed since last research on this topic."""
        assert self._db is not None

        async with self._db.execute(
            "SELECT last_researched_at FROM interest_research_log WHERE topic = ?",
            (topic,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return True  # Never researched, should research

        last_researched = datetime.fromisoformat(row[0])
        age_hours = (datetime.utcnow() - last_researched).total_seconds() / 3600

        return age_hours >= cooldown_hours

    # Opportunity operations

    async def add_opportunity(self, opp: Opportunity) -> None:
        """Add an opportunity."""
        assert self._db is not None
        await self._db.execute(
            """
            INSERT OR REPLACE INTO opportunities
            (id, title, description, source_url, relevance_score, matched_interests, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                opp.id,
                opp.title,
                opp.description,
                opp.source_url,
                opp.relevance_score,
                json.dumps(opp.matched_interests),
                opp.created_at,
                opp.status,
            ),
        )
        await self._db.commit()

    async def get_opportunities(
        self, status: str | None = None, limit: int = 20
    ) -> list[Opportunity]:
        """Get opportunities, optionally filtered by status."""
        assert self._db is not None
        query = "SELECT * FROM opportunities"
        params: list[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        opps = []
        async with self._db.execute(query, params) as cursor:
            async for row in cursor:
                opps.append(
                    Opportunity(
                        id=row[0],
                        title=row[1],
                        description=row[2],
                        source_url=row[3],
                        relevance_score=row[4],
                        matched_interests=json.loads(row[5]),
                        created_at=row[6],
                        status=row[7],
                    )
                )
        return opps

    async def update_opportunity_status(self, id: str, status: str) -> None:
        """Update opportunity status."""
        assert self._db is not None
        await self._db.execute(
            "UPDATE opportunities SET status = ? WHERE id = ?", (status, id)
        )
        await self._db.commit()

    # Feedback operations

    async def add_feedback(self, feedback: Feedback) -> None:
        """Add user feedback."""
        assert self._db is not None
        await self._db.execute(
            """
            INSERT INTO feedback (id, job_id, feedback_type, comment, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                feedback.id,
                feedback.job_id,
                feedback.feedback_type,
                feedback.comment,
                feedback.created_at,
            ),
        )
        await self._db.commit()

    async def get_feedback(self, job_id: str) -> Feedback | None:
        """Get feedback for a job."""
        assert self._db is not None
        async with self._db.execute(
            "SELECT * FROM feedback WHERE job_id = ?", (job_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return Feedback.from_dict(dict(zip(["id", "job_id", "feedback_type", "comment", "created_at"], row)))
            return None

    # Job operations

    async def create_job(
        self,
        job_id: str,
        command_type: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Create a new job."""
        assert self._db is not None
        now = datetime.utcnow().isoformat()
        await self._db.execute(
            """
            INSERT INTO jobs (id, command_type, status, context, created_at, updated_at)
            VALUES (?, ?, 'pending', ?, ?, ?)
            """,
            (job_id, command_type, json.dumps(context), now, now),
        )
        await self._db.commit()

    async def update_job_status(
        self, job_id: str, status: str, completed_at: str | None = None
    ) -> None:
        """Update job status."""
        assert self._db is not None
        now = datetime.utcnow().isoformat()
        await self._db.execute(
            """
            UPDATE jobs
            SET status = ?, updated_at = ?, completed_at = ?
            WHERE id = ?
            """,
            (status, now, completed_at, job_id),
        )
        await self._db.commit()

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        """Get job by ID."""
        assert self._db is not None
        async with self._db.execute(
            "SELECT * FROM jobs WHERE id = ?", (job_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "command_type": row[1],
                    "status": row[2],
                    "context": json.loads(row[3]) if row[3] else None,
                    "created_at": row[4],
                    "updated_at": row[5],
                    "completed_at": row[6],
                }
            return None

    # Proposal operations (D6)

    async def add_proposal(self, proposal: Proposal) -> None:
        """Add a self-modification proposal."""
        assert self._db is not None
        now = datetime.utcnow().isoformat()
        proposal.created_at = proposal.created_at or now
        await self._db.execute(
            """
            INSERT INTO proposals
            (id, proposal_type, description, rationale, code_diff, status, created_at, reviewed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                proposal.id,
                proposal.proposal_type,
                proposal.description,
                proposal.rationale,
                proposal.code_diff,
                proposal.status,
                proposal.created_at,
                proposal.reviewed_at,
            ),
        )
        await self._db.commit()

    async def get_pending_proposals(self) -> list[Proposal]:
        """Get all pending proposals."""
        assert self._db is not None
        proposals = []
        async with self._db.execute(
            "SELECT * FROM proposals WHERE status = 'pending' ORDER BY created_at"
        ) as cursor:
            async for row in cursor:
                proposals.append(
                    Proposal(
                        id=row[0],
                        proposal_type=row[1],
                        description=row[2],
                        rationale=row[3],
                        code_diff=row[4],
                        status=row[5],
                        created_at=row[6],
                        reviewed_at=row[7],
                    )
                )
        return proposals

    async def update_proposal_status(
        self, proposal_id: str, status: str
    ) -> None:
        """Update proposal status."""
        assert self._db is not None
        now = datetime.utcnow().isoformat()
        await self._db.execute(
            """
            UPDATE proposals
            SET status = ?, reviewed_at = ?
            WHERE id = ?
            """,
            (status, now, proposal_id),
        )
        await self._db.commit()

    # Embedding cache operations (for hybrid classification)

    async def upsert_interest_embedding(
        self, interest_id: str, embedding: list[float], model_version: str
    ) -> None:
        """Store embedding for an interest label."""
        assert self._db is not None
        import array
        import datetime
        
        now = datetime.datetime.utcnow().isoformat()
        # Convert float list to bytes for storage
        embedding_bytes = array.array('f', embedding).tobytes()
        
        await self._db.execute(
            """
            INSERT INTO interest_embeddings (interest_id, embedding, model_version, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(interest_id) DO UPDATE SET
                embedding = ?,
                model_version = ?,
                updated_at = ?
            """,
            (interest_id, embedding_bytes, model_version, now, embedding_bytes, model_version, now),
        )
        await self._db.commit()

    async def get_interest_embedding(self, interest_id: str) -> list[float] | None:
        """Get embedding for a specific interest."""
        assert self._db is not None
        import array
        
        async with self._db.execute(
            "SELECT embedding FROM interest_embeddings WHERE interest_id = ?",
            (interest_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                embedding_array = array.array('f', row[0])
                return list(embedding_array)
            return None

    async def get_interest_embeddings(
        self, min_strength: float = 0.2
    ) -> list[tuple[str, list[float]]]:
        """
        Get (interest_id, embedding) pairs for interests above strength threshold.
        
        Returns empty list if no embeddings are cached.
        """
        assert self._db is not None
        import array
        
        query = """
            SELECT e.interest_id, e.embedding
            FROM interest_embeddings e
            JOIN interest_nodes n ON e.interest_id = n.id
            WHERE n.strength >= ?
        """
        
        results = []
        async with self._db.execute(query, (min_strength,)) as cursor:
            async for row in cursor:
                interest_id = row[0]
                embedding_array = array.array('f', row[1])
                embedding = list(embedding_array)
                results.append((interest_id, embedding))
        
        return results

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        import math
        
        dot_product = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return dot_product / (norm_a * norm_b)

    # Interest-Concept linking operations

    async def add_interest_concept_link(
        self,
        interest_id: str,
        concept_id: str,
        link_type: str,
        confidence: float,
    ) -> None:
        """
        Link an interest to a concept node.
        
        Args:
            interest_id: ID of the interest
            concept_id: ID of the concept node
            link_type: "exact_match", "related_to", "broader", "narrower"
            confidence: Link confidence 0.0-1.0
        """
        assert self._db is not None
        now = datetime.utcnow().isoformat()
        
        await self._db.execute(
            """
            INSERT INTO interest_concept_links
            (interest_id, concept_id, link_type, confidence, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(interest_id, concept_id) DO UPDATE SET
                link_type = ?,
                confidence = ?
            """,
            (interest_id, concept_id, link_type, confidence, now, link_type, confidence),
        )
        await self._db.commit()

    async def get_linked_concepts(self, interest_id: str) -> list[str]:
        """Get concept IDs linked to an interest."""
        assert self._db is not None
        
        async with self._db.execute(
            "SELECT concept_id FROM interest_concept_links WHERE interest_id = ?",
            (interest_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def get_linked_interests(self, concept_id: str) -> list[str]:
        """Get interest IDs linked to a concept."""
        assert self._db is not None
        
        async with self._db.execute(
            "SELECT interest_id FROM interest_concept_links WHERE concept_id = ?",
            (concept_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def remove_interest_concept_link(
        self, interest_id: str, concept_id: str
    ) -> None:
        """Remove a link between interest and concept."""
        assert self._db is not None
        
        await self._db.execute(
            "DELETE FROM interest_concept_links WHERE interest_id = ? AND concept_id = ?",
            (interest_id, concept_id),
        )
        await self._db.commit()
