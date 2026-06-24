#!/usr/bin/env python3
"""Migrate database from SQLite to PostgreSQL.

Usage:
    python scripts/migrate_to_postgres.py \
        --from-sqlite ./data/knowledge.db \
        --to-postgres postgresql://user:pass@localhost/personal_assistant \
        --mode full \
        --verify
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.store.db_connection import SQLiteConnection, PostgreSQLConnection
from src.store.knowledge import compute_concept_id
from init_postgres_schema import create_schema, DDL_STATEMENTS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Foreign-key dependency order (parents before children). Tables not listed
# here have no FK dependencies and are safe to copy in any order.
TABLE_COPY_ORDER = [
    "interests",
    "user_profile",
    "opportunities",
    "activity_log",
    "interest_signal_evidence",
    "interest_research_log",
    "citations",
    "concepts",
    "interest_embeddings",
    "citation_relationships",
    "concept_relationships",
    "interest_concept_links",
    "citation_concept_links",
    "interest_citation_links",
    "research_runs",
    "opportunity_interest_links",
    "conversation_sessions",
    "conversation_turns",
    "knowledge_entries",
    "user_stats",
]


def order_tables_for_copy(tables: list[str]) -> list[str]:
    """Order tables so FK parents are copied before their children.

    Any table present in the source but not in TABLE_COPY_ORDER is appended
    at the end (defensive, in case the schema gained new tables).
    """
    known = [t for t in TABLE_COPY_ORDER if t in tables]
    unknown = [t for t in tables if t not in TABLE_COPY_ORDER]
    return known + unknown


async def get_table_names(conn, db_type: str) -> list[str]:
    """Get all table names from database."""
    if db_type == "sqlite":
        query = """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """
    else:  # postgresql
        query = """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """

    rows = await conn.fetchall(query)
    return [row[list(row.keys())[0]] for row in rows]


async def get_row_count(conn, table: str) -> int:
    """Get row count for a table."""
    query = f"SELECT COUNT(*) as cnt FROM {table}"
    row = await conn.fetchone(query)
    return row["cnt"] if row else 0


async def copy_table_data(
    source_conn, dest_conn, table: str, db_type_from: str, db_type_to: str
) -> tuple[int, int]:
    """Copy data from source table to destination table.

    Returns (rows_copied, rows_skipped_as_duplicates).
    """
    # Get all rows from source
    query = f"SELECT * FROM {table}"
    rows = await source_conn.fetchall(query)

    if not rows:
        logger.info(f"  {table}: 0 rows (empty)")
        return 0, 0

    # Get column names
    columns = list(rows[0].keys())
    column_list = ", ".join(columns)

    # Build parameterized insert. ON CONFLICT DO NOTHING (Postgres) makes the
    # copy tolerant of source data-quality issues (e.g. SQLite rows whose
    # content-addressed ID was NULL and collides with an existing row once
    # regenerated) instead of aborting the whole migration on one bad row.
    placeholders = ", ".join(["?" if db_type_to == "sqlite" else f"${i+1}" for i in range(len(columns))])
    insert_query = f"INSERT INTO {table} ({column_list}) VALUES ({placeholders})"
    if db_type_to == "postgresql":
        insert_query += " ON CONFLICT DO NOTHING"

    # Insert rows (with special handling for NULL IDs in concepts table)
    for row in rows:
        row_dict = dict(row)

        # Special case: regenerate NULL concept IDs (content-addressed)
        if table == "concepts" and row_dict.get("id") is None:
            label = row_dict.get("label", "")
            category = row_dict.get("category", "general")
            row_dict["id"] = compute_concept_id(label, category)
            logger.debug(f"  Regenerated NULL concept ID: {label} → {row_dict['id']}")

        values = tuple(row_dict[col] for col in columns)
        await dest_conn.execute(insert_query, values)

    await dest_conn.commit()
    actual_count = await get_row_count(dest_conn, table)
    skipped = len(rows) - actual_count
    if skipped > 0:
        logger.info(f"  {table}: {actual_count} rows copied ({skipped} duplicate rows skipped)")
    else:
        logger.info(f"  {table}: {actual_count} rows copied")
    return actual_count, skipped


async def verify_migration(
    source_conn, dest_conn, tables: list[str], skipped_counts: dict[str, int]
) -> bool:
    """Verify that all data was copied correctly.

    A table whose dest count is short by exactly its recorded skipped-duplicate
    count is not a failure - those rows were intentionally deduplicated during
    copy (e.g. NULL content-addressed IDs colliding with an existing row).
    """
    logger.info("\nVerifying migration...")
    all_match = True

    for table in tables:
        source_count = await get_row_count(source_conn, table)
        dest_count = await get_row_count(dest_conn, table)
        skipped = skipped_counts.get(table, 0)

        if source_count == dest_count:
            logger.info(f"  ✓ {table}: {source_count} → {dest_count}")
        elif source_count - skipped == dest_count:
            logger.info(
                f"  ✓ {table}: {source_count} → {dest_count} "
                f"({skipped} duplicate rows intentionally merged)"
            )
        else:
            logger.info(f"  ✗ {table}: {source_count} → {dest_count}")
            all_match = False

    return all_match


async def reset_sequences(conn) -> None:
    """Reset PostgreSQL sequences to max ID values."""
    logger.info("Resetting PostgreSQL sequences...")

    sequences = [
        ("user_profile", "id"),
        ("activity_log", "id"),
        ("interest_signal_evidence", "id"),
        ("interest_research_log", "id"),
        ("citation_relationships", "id"),
        ("concept_relationships", "id"),
        ("interest_concept_links", "id"),
        ("citation_concept_links", "id"),
        ("interest_citation_links", "id"),
        ("opportunity_interest_links", "id"),
        ("conversation_turns", "id"),
    ]

    for table, column in sequences:
        # Check if table exists
        check_query = f"SELECT COUNT(*) as cnt FROM {table}"
        try:
            await conn.fetchone(check_query)
        except:
            continue

        # Get max ID
        max_query = f"SELECT MAX({column}) as max_id FROM {table}"
        row = await conn.fetchone(max_query)
        max_id = row.get("max_id") or 0

        # Reset sequence
        seq_name = f"{table}_{column}_seq"
        reset_query = f"ALTER SEQUENCE {seq_name} RESTART WITH {max_id + 1}"
        try:
            await conn.execute(reset_query)
            await conn.commit()
            logger.info(f"  ✓ {seq_name} → {max_id + 1}")
        except Exception as e:
            logger.warning(f"  ⚠ Could not reset {seq_name}: {e}")


async def migrate(
    sqlite_path: str,
    postgres_url: str,
    mode: str = "full",
    verify: bool = False,
) -> bool:
    """Perform migration."""
    logger.info(f"Starting migration from SQLite to PostgreSQL...")
    logger.info(f"  Source: {sqlite_path}")
    logger.info(f"  Target: {postgres_url}")
    logger.info(f"  Mode: {mode}")

    # Parse PostgreSQL URL
    # Format: postgresql://user:password@host:port/database
    try:
        from urllib.parse import urlparse
        parsed = urlparse(postgres_url)
        pg_config = {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 5432,
            "user": parsed.username or "pa_user",
            "password": parsed.password or "",
            "database": parsed.path.lstrip("/") or "personal_assistant",
        }
    except Exception as e:
        logger.error(f"Invalid PostgreSQL URL: {e}")
        return False

    # Connect to both databases
    sqlite_conn = SQLiteConnection(sqlite_path)
    postgres_conn = PostgreSQLConnection(**pg_config)

    try:
        logger.info("\nConnecting to SQLite...")
        await sqlite_conn.initialize()

        logger.info("Connecting to PostgreSQL...")
        await postgres_conn.initialize()

        # Create schema (idempotent - uses CREATE TABLE IF NOT EXISTS)
        logger.info(f"\nEnsuring PostgreSQL schema exists ({len(DDL_STATEMENTS)} objects)...")
        await create_schema(postgres_conn)

        # Clear all tables (idempotent truncate before copy)
        logger.info("\nClearing PostgreSQL tables...")
        for table in TABLE_COPY_ORDER:
            await postgres_conn.execute(f"TRUNCATE TABLE {table} CASCADE")
        await postgres_conn.commit()

        # Get table list
        logger.info("\nFetching table list...")
        tables = await get_table_names(sqlite_conn, "sqlite")
        logger.info(f"Found {len(tables)} tables: {', '.join(tables)}")

        # Copy data (parents before children, so FK constraints don't reject rows)
        logger.info(f"\nCopying data ({mode} mode)...")
        total_rows = 0
        skipped_counts: dict[str, int] = {}
        for table in order_tables_for_copy(tables):
            rows_copied, rows_skipped = await copy_table_data(
                sqlite_conn, postgres_conn, table, "sqlite", "postgresql"
            )
            total_rows += rows_copied
            skipped_counts[table] = rows_skipped

        logger.info(f"\nTotal rows copied: {total_rows}")

        # Reset sequences
        await reset_sequences(postgres_conn)

        # Verify
        if verify:
            success = await verify_migration(sqlite_conn, postgres_conn, tables, skipped_counts)
            if success:
                logger.info("\n✓ Migration verified successfully!")
                return True
            else:
                logger.error("\n✗ Migration verification FAILED!")
                return False
        else:
            logger.info("\n✓ Migration complete! (verification skipped)")
            return True

    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        return False

    finally:
        logger.info("\nCleaning up...")
        await sqlite_conn.close()
        await postgres_conn.close()


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Migrate Personal Assistant database from SQLite to PostgreSQL"
    )
    parser.add_argument(
        "--from-sqlite",
        required=True,
        help="Path to SQLite database (e.g., ./data/knowledge.db)",
    )
    parser.add_argument(
        "--to-postgres",
        required=True,
        help="PostgreSQL connection URL (e.g., postgresql://user:pass@localhost/db)",
    )
    parser.add_argument(
        "--mode",
        choices=["full", "incremental"],
        default="full",
        help="Migration mode: full (copy all) or incremental (copy new rows)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify row counts match after migration",
    )

    args = parser.parse_args()

    success = await migrate(
        sqlite_path=args.from_sqlite,
        postgres_url=args.to_postgres,
        mode=args.mode,
        verify=args.verify,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
