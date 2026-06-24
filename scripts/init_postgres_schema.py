#!/usr/bin/env python3
"""Initialize PostgreSQL schema for Personal Assistant.

Creates all 20 tables (+ indexes) mirroring src/store/knowledge.py's SQLite schema,
translated to PostgreSQL types (SERIAL for AUTOINCREMENT, BYTEA for BLOB, etc).

Usage:
    python scripts/init_postgres_schema.py \
        --host localhost --port 5433 \
        --user pa_user --password <password> \
        --database personal_assistant
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.store.db_connection import PostgreSQLConnection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


DDL_STATEMENTS = [
    # ===== USER MEMORY TABLES =====
    """
    CREATE TABLE IF NOT EXISTS interests (
        id TEXT PRIMARY KEY,
        label TEXT NOT NULL,
        strength DOUBLE PRECISION DEFAULT 0.5,
        embeddings_cached INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        last_active TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS interest_embeddings (
        interest_id TEXT PRIMARY KEY,
        embedding BYTEA NOT NULL,
        model_version TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (interest_id) REFERENCES interests(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_profile (
        id SERIAL PRIMARY KEY,
        key TEXT UNIQUE NOT NULL,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS opportunities (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        description TEXT,
        relevance_score DOUBLE PRECISION DEFAULT 0.5,
        source TEXT,
        url TEXT,
        created_at TEXT NOT NULL,
        metadata TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS activity_log (
        id SERIAL PRIMARY KEY,
        timestamp TEXT NOT NULL,
        activity_type TEXT NOT NULL,
        description TEXT,
        raw_data TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS interest_signal_evidence (
        id SERIAL PRIMARY KEY,
        signal_id TEXT NOT NULL,
        topic TEXT NOT NULL,
        confidence DOUBLE PRECISION NOT NULL,
        timestamp TEXT NOT NULL,
        UNIQUE(signal_id, topic)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS interest_research_log (
        id SERIAL PRIMARY KEY,
        topic TEXT UNIQUE NOT NULL,
        last_researched_at TEXT NOT NULL
    )
    """,
    # ===== CITATION GRAPH TABLES =====
    """
    CREATE TABLE IF NOT EXISTS citations (
        id TEXT PRIMARY KEY,
        arxiv_id TEXT UNIQUE,
        doi TEXT UNIQUE,
        title TEXT NOT NULL,
        abstract TEXT,
        authors TEXT,
        published_date TEXT,
        journal TEXT,
        categories TEXT,
        citation_count INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        semantic_scholar_id TEXT,
        url TEXT,
        tldr TEXT,
        conclusion TEXT,
        notes TEXT,
        year INTEGER,
        venue TEXT,
        reference_count INTEGER DEFAULT 0,
        influential_citation_count INTEGER DEFAULT 0,
        source TEXT,
        last_researched_at TEXT,
        embedding_cached INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS citation_relationships (
        id SERIAL PRIMARY KEY,
        source_id TEXT NOT NULL,
        target_id TEXT NOT NULL,
        relationship_type TEXT NOT NULL DEFAULT 'cites',
        UNIQUE(source_id, target_id, relationship_type),
        FOREIGN KEY (source_id) REFERENCES citations(id),
        FOREIGN KEY (target_id) REFERENCES citations(id)
    )
    """,
    # ===== KNOWLEDGE GRAPH TABLES =====
    """
    CREATE TABLE IF NOT EXISTS concepts (
        id TEXT PRIMARY KEY,
        label TEXT NOT NULL,
        description TEXT,
        category TEXT,
        created_at TEXT NOT NULL,
        mention_count INTEGER DEFAULT 0,
        first_seen_run_id TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS concept_relationships (
        id SERIAL PRIMARY KEY,
        source_id TEXT NOT NULL,
        target_id TEXT NOT NULL,
        relation_type TEXT NOT NULL,
        weight DOUBLE PRECISION DEFAULT 1.0,
        FOREIGN KEY (source_id) REFERENCES concepts(id),
        FOREIGN KEY (target_id) REFERENCES concepts(id)
    )
    """,
    # ===== CROSS-REFERENCE TABLES =====
    """
    CREATE TABLE IF NOT EXISTS interest_concept_links (
        id SERIAL PRIMARY KEY,
        interest_id TEXT NOT NULL,
        concept_id TEXT NOT NULL,
        link_type TEXT DEFAULT 'related',
        confidence DOUBLE PRECISION DEFAULT 0.8,
        created_at TEXT NOT NULL,
        FOREIGN KEY (interest_id) REFERENCES interests(id) ON DELETE CASCADE,
        FOREIGN KEY (concept_id) REFERENCES concepts(id) ON DELETE CASCADE,
        UNIQUE(interest_id, concept_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS citation_concept_links (
        id SERIAL PRIMARY KEY,
        citation_id TEXT NOT NULL,
        concept_id TEXT NOT NULL,
        relation_type TEXT DEFAULT 'discusses',
        evidence_text TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (citation_id) REFERENCES citations(id) ON DELETE CASCADE,
        FOREIGN KEY (concept_id) REFERENCES concepts(id) ON DELETE CASCADE,
        UNIQUE(citation_id, concept_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS interest_citation_links (
        id SERIAL PRIMARY KEY,
        interest_id TEXT NOT NULL,
        citation_id TEXT NOT NULL,
        relevance DOUBLE PRECISION DEFAULT 0.5,
        discovered_run_id TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (interest_id) REFERENCES interests(id) ON DELETE CASCADE,
        FOREIGN KEY (citation_id) REFERENCES citations(id) ON DELETE CASCADE,
        UNIQUE(interest_id, citation_id)
    )
    """,
    """
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
    """,
    """
    CREATE TABLE IF NOT EXISTS opportunity_interest_links (
        id SERIAL PRIMARY KEY,
        opportunity_id TEXT NOT NULL,
        interest_id TEXT NOT NULL,
        relevance_score DOUBLE PRECISION DEFAULT 0.5,
        created_at TEXT NOT NULL,
        FOREIGN KEY (opportunity_id) REFERENCES opportunities(id) ON DELETE CASCADE,
        FOREIGN KEY (interest_id) REFERENCES interests(id) ON DELETE CASCADE,
        UNIQUE(opportunity_id, interest_id)
    )
    """,
    # ===== CONVERSATION HISTORY TABLES =====
    """
    CREATE TABLE IF NOT EXISTS conversation_sessions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        question_count INTEGER DEFAULT 0,
        metadata TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS conversation_turns (
        id SERIAL PRIMARY KEY,
        session_id TEXT NOT NULL,
        turn_number INTEGER NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        metadata TEXT,
        FOREIGN KEY (session_id) REFERENCES conversation_sessions(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_entries (
        id TEXT PRIMARY KEY,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        quality_score DOUBLE PRECISION DEFAULT 0.5,
        source_session_id TEXT,
        user_id TEXT NOT NULL,
        embedded INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        metadata TEXT,
        FOREIGN KEY (source_session_id) REFERENCES conversation_sessions(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_stats (
        user_id TEXT PRIMARY KEY,
        total_questions INTEGER DEFAULT 0,
        total_knowledge_entries INTEGER DEFAULT 0,
        last_active TEXT,
        updated_at TEXT NOT NULL
    )
    """,
    # ===== INDEXES =====
    "CREATE INDEX IF NOT EXISTS idx_interests_strength ON interests(strength)",
    "CREATE INDEX IF NOT EXISTS idx_interests_label ON interests(label)",
    "CREATE INDEX IF NOT EXISTS idx_concepts_label ON concepts(label)",
    "CREATE INDEX IF NOT EXISTS idx_citations_published ON citations(published_date)",
    "CREATE INDEX IF NOT EXISTS idx_interest_concept ON interest_concept_links(interest_id)",
    "CREATE INDEX IF NOT EXISTS idx_citation_concept ON citation_concept_links(citation_id)",
    "CREATE INDEX IF NOT EXISTS idx_citation_rel_source ON citation_relationships(source_id)",
    "CREATE INDEX IF NOT EXISTS idx_citation_rel_target ON citation_relationships(target_id)",
    "CREATE INDEX IF NOT EXISTS idx_interest_citation ON interest_citation_links(interest_id)",
    "CREATE INDEX IF NOT EXISTS idx_research_runs_topic ON research_runs(topic)",
    "CREATE INDEX IF NOT EXISTS idx_research_runs_interest ON research_runs(interest_id)",
    "CREATE INDEX IF NOT EXISTS idx_conversation_sessions_user ON conversation_sessions(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_conversation_turns_session ON conversation_turns(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_entries_user ON knowledge_entries(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_entries_quality ON knowledge_entries(quality_score DESC)",
]


async def create_schema(conn: PostgreSQLConnection) -> None:
    """Execute all DDL statements to build the schema."""
    for statement in DDL_STATEMENTS:
        await conn.execute(statement)
    await conn.commit()


async def main():
    """Initialize PostgreSQL schema."""
    parser = argparse.ArgumentParser(
        description="Initialize PostgreSQL schema for Personal Assistant"
    )
    parser.add_argument("--host", default="localhost", help="PostgreSQL host")
    parser.add_argument("--port", type=int, default=5432, help="PostgreSQL port")
    parser.add_argument("--user", default="pa_user", help="PostgreSQL user")
    parser.add_argument("--password", default="", help="PostgreSQL password")
    parser.add_argument(
        "--database", default="personal_assistant", help="PostgreSQL database"
    )

    args = parser.parse_args()

    logger.info(
        f"Connecting to PostgreSQL: {args.user}@{args.host}:{args.port}/{args.database}"
    )

    conn = PostgreSQLConnection(
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
        database=args.database,
        ssl="disable",
    )

    try:
        await conn.initialize()
        logger.info(f"Creating {len(DDL_STATEMENTS)} schema objects...")
        await create_schema(conn)
        logger.info("✓ PostgreSQL schema created successfully!")
    except Exception as e:
        logger.error(f"Failed to initialize schema: {e}", exc_info=True)
        sys.exit(1)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
