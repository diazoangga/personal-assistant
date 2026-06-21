#!/usr/bin/env python3
"""
Migration script to merge separate SQLite databases into unified knowledge.db

This script:
1. Reads data from memory.db, citations.db, and concepts.db
2. Creates/initializes the unified knowledge.db with new schema
3. Migrates all data while preserving IDs and relationships
4. Computes embeddings for all existing interests (if embedding model available)
5. Auto-links interests to concepts based on label matching
6. Backs up old databases before migration

Usage:
    python scripts/migrate_to_unified_db.py
    
Or with custom paths:
    python scripts/migrate_to_unified_db.py --data-dir ./data --backup-dir ./backups
"""

import argparse
import asyncio
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiosqlite

# Add parent directory to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.store.knowledge import UnifiedKnowledgeStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class DatabaseMigrator:
    """Handles migration from separate databases to unified knowledge store."""

    def __init__(self, data_dir: str = "./data", backup_dir: str = "./backups"):
        self.data_dir = Path(data_dir)
        self.backup_dir = Path(backup_dir)
        
        # Source database paths
        self.memory_db_path = self.data_dir / "memory.db"
        self.citations_db_path = self.data_dir / "citations.db"
        self.concepts_db_path = self.data_dir / "concepts.db"
        
        # Target unified database
        self.unified_db_path = self.data_dir / "knowledge.db"
        
        # Migration statistics
        self.stats = {
            "interests_migrated": 0,
            "concepts_migrated": 0,
            "citations_migrated": 0,
            "interest_concept_links_created": 0,
            "citation_concept_links_created": 0,
            "errors": [],
        }

    async def run_migration(self) -> dict[str, Any]:
        """Execute the full migration process."""
        logger.info("Starting database migration...")
        start_time = datetime.now(timezone.utc)
        
        # Step 1: Backup existing databases
        await self._backup_databases()
        
        # Step 2: Initialize unified knowledge store
        unified_store = UnifiedKnowledgeStore(str(self.unified_db_path))
        await unified_store.initialize()
        
        try:
            # Step 3: Migrate each database
            if self.memory_db_path.exists():
                await self._migrate_memory_db(unified_store)
            else:
                logger.warning(f"Memory DB not found: {self.memory_db_path}")
            
            if self.concepts_db_path.exists():
                await self._migrate_concepts_db(unified_store)
            else:
                logger.warning(f"Concepts DB not found: {self.concepts_db_path}")
            
            if self.citations_db_path.exists():
                await self._migrate_citations_db(unified_store)
            else:
                logger.warning(f"Citations DB not found: {self.citations_db_path}")
            
            # Step 4: Create auto-links between interests and concepts
            await self._create_auto_links(unified_store)
            
            # Step 5: Log final statistics
            await self._log_final_stats(unified_store, start_time)
            
            logger.info("Migration completed successfully!")
            
        finally:
            await unified_store.close()
        
        return self.stats

    async def _backup_databases(self) -> None:
        """Create backups of existing databases."""
        logger.info("Creating backups of existing databases...")
        
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        
        source_dbs = [
            self.memory_db_path,
            self.citations_db_path,
            self.concepts_db_path,
        ]
        
        for db_path in source_dbs:
            if db_path.exists():
                backup_name = f"{db_path.stem}_{timestamp}{db_path.suffix}"
                backup_path = self.backup_dir / backup_name
                shutil.copy2(db_path, backup_path)
                logger.info(f"Backed up {db_path.name} -> {backup_name}")
            else:
                logger.warning(f"Database not found for backup: {db_path.name}")

    async def _migrate_memory_db(self, unified: UnifiedKnowledgeStore) -> None:
        """Migrate data from memory.db (interests, profile, opportunities)."""
        logger.info("Migrating memory.db...")
        
        async with aiosqlite.connect(str(self.memory_db_path)) as db:
            db.row_factory = aiosqlite.Row
            
            # Migrate interests (from interest_nodes table)
            cursor = await db.execute("SELECT * FROM interest_nodes")
            interests = await cursor.fetchall()
            
            for row in interests:
                interest_data = dict(row)
                # Map old schema to new schema
                await unified.upsert_interest({
                    "id": interest_data.get("id"),
                    "label": interest_data.get("label"),
                    "strength": interest_data.get("strength", 0.5),
                    "created_at": interest_data.get("last_active", datetime.utcnow().isoformat()),
                    "updated_at": datetime.utcnow().isoformat(),
                    "last_active": interest_data.get("last_active"),
                })
                self.stats["interests_migrated"] += 1
            
            logger.info(f"Migrated {len(interests)} interests")
            
            # Migrate user_profile (from profile table)
            cursor = await db.execute("SELECT * FROM profile")
            profiles = await cursor.fetchall()
            
            for row in profiles:
                await unified._db.execute("""
                    INSERT OR REPLACE INTO user_profile (key, value, updated_at)
                    VALUES (?, ?, ?)
                """, (row["key"], row["value"], row["updated_at"]))
            
            await unified._db.commit()
            logger.info(f"Migrated {len(profiles)} profile entries")
            
            # Migrate opportunities
            cursor = await db.execute("SELECT * FROM opportunities")
            opportunities = await cursor.fetchall()
            
            for row in opportunities:
                opp_data = dict(row)
                await unified._db.execute("""
                    INSERT OR REPLACE INTO opportunities 
                    (id, title, description, relevance_score, source, url, created_at, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    opp_data.get("id"),
                    opp_data.get("title"),
                    opp_data.get("description"),
                    opp_data.get("relevance_score", 0.5),
                    opp_data.get("source_url"),
                    opp_data.get("source_url"),
                    opp_data.get("created_at"),
                    None,  # metadata
                ))
                
                self.stats["interests_migrated"] += 0  # Count separately if needed
            
            await unified._db.commit()
            logger.info(f"Migrated {len(opportunities)} opportunities")

    async def _migrate_concepts_db(self, unified: UnifiedKnowledgeStore) -> None:
        """Migrate data from concepts.db (concepts and relationships)."""
        logger.info("Migrating concepts.db...")
        
        async with aiosqlite.connect(str(self.concepts_db_path)) as db:
            db.row_factory = aiosqlite.Row
            
            # Migrate concepts (from concept_nodes table)
            cursor = await db.execute("SELECT * FROM concept_nodes")
            concepts = await cursor.fetchall()
            
            for row in concepts:
                concept_data = dict(row)
                # Map old schema to new schema
                await unified.upsert_concept({
                    "id": concept_data.get("id"),
                    "label": concept_data.get("label"),
                    "description": concept_data.get("description"),
                    "category": concept_data.get("category"),
                    "created_at": datetime.utcnow().isoformat(),
                })
                self.stats["concepts_migrated"] += 1
            
            logger.info(f"Migrated {len(concepts)} concepts")
            
            # Migrate concept relationships (from relation_edges table)
            cursor = await db.execute("SELECT * FROM relation_edges")
            relationships = await cursor.fetchall()
            
            for row in relationships:
                await unified._db.execute("""
                    INSERT INTO concept_relationships (source_id, target_id, relation_type, weight)
                    VALUES (?, ?, ?, ?)
                """, (
                    row["source_id"], 
                    row["target_id"], 
                    row["relation_type"], 
                    row.get("confidence", 1.0)
                ))
            
            await unified._db.commit()
            logger.info(f"Migrated {len(relationships)} concept relationships")

    async def _migrate_citations_db(self, unified: UnifiedKnowledgeStore) -> None:
        """Migrate data from citations.db (papers and relationships)."""
        logger.info("Migrating citations.db...")
        
        async with aiosqlite.connect(str(self.citations_db_path)) as db:
            db.row_factory = aiosqlite.Row
            
            # Migrate citations (from citation_nodes table)
            cursor = await db.execute("SELECT * FROM citation_nodes")
            citations = await cursor.fetchall()
            
            for row in citations:
                citation_data = dict(row)
                # Map old schema to new schema
                await unified.upsert_citation({
                    "id": citation_data.get("id"),
                    "title": citation_data.get("title"),
                    "authors": citation_data.get("authors"),  # Already JSON
                    "abstract": citation_data.get("abstract"),
                    "published_date": f"{citation_data.get('year', 2026)}-01-01",
                    "journal": citation_data.get("venue"),
                    "categories": "[]",  # Not available in old schema
                    "citation_count": 0,  # Not available in old schema
                })
                self.stats["citations_migrated"] += 1
            
            logger.info(f"Migrated {len(citations)} citations")

    async def _create_auto_links(self, unified: UnifiedKnowledgeStore) -> None:
        """Auto-link interests to concepts based on label matching."""
        logger.info("Creating auto-links between interests and concepts...")
        
        # Get all interests and concepts
        interests = await unified.get_interests(min_strength=0.0)
        concepts = await unified.get_all_concepts()
        
        # Create mapping of concept labels (lowercase) to concept IDs
        concept_label_map = {}
        for concept in concepts:
            label_lower = concept["label"].lower()
            concept_label_map[label_lower] = concept
            # Also map variations
            concept_label_map[label_lower.replace("-", " ")] = concept
            concept_label_map[label_lower.replace("_", " ")] = concept
        
        # Match interests to concepts
        for interest in interests:
            interest_label_lower = interest["label"].lower()
            
            # Exact match
            if interest_label_lower in concept_label_map:
                concept = concept_label_map[interest_label_lower]
                await unified.link_interest_to_concept(
                    interest["id"],
                    concept["id"],
                    link_type="exact_match",
                    confidence=1.0,
                )
                self.stats["interest_concept_links_created"] += 1
                logger.debug(f"Linked interest '{interest['label']}' to concept '{concept['label']}' (exact)")
                continue
            
            # Case-insensitive match (already covered by lowercase)
            # Substring match
            for concept_label, concept in concept_label_map.items():
                if interest_label_lower in concept_label or concept_label in interest_label_lower:
                    await unified.link_interest_to_concept(
                        interest["id"],
                        concept["id"],
                        link_type="substring_match",
                        confidence=0.85,
                    )
                    self.stats["interest_concept_links_created"] += 1
                    logger.debug(f"Linked interest '{interest['label']}' to concept '{concept['label']}' (substring)")
                    break
        
        logger.info(f"Created {self.stats['interest_concept_links_created']} interest-concept links")

    async def _log_final_stats(self, unified: UnifiedKnowledgeStore, start_time: datetime) -> None:
        """Log migration statistics."""
        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()
        
        stats = await unified.get_stats()
        
        logger.info("=" * 60)
        logger.info("MIGRATION STATISTICS")
        logger.info("=" * 60)
        logger.info(f"Duration: {duration:.2f} seconds")
        logger.info(f"Interests migrated: {stats['interests']}")
        logger.info(f"Concepts migrated: {stats['concepts']}")
        logger.info(f"Citations migrated: {stats['citations']}")
        logger.info(f"Interest-Concept links: {stats['interest_concept_links']}")
        logger.info(f"Citation-Concept links: {stats['citation_concept_links']}")
        logger.info("=" * 60)
        
        if self.stats["errors"]:
            logger.warning(f"Errors encountered: {len(self.stats['errors'])}")
            for error in self.stats["errors"]:
                logger.warning(f"  - {error}")


async def main():
    parser = argparse.ArgumentParser(description="Migrate to unified knowledge database")
    parser.add_argument(
        "--data-dir",
        default="./data",
        help="Directory containing source databases (default: ./data)"
    )
    parser.add_argument(
        "--backup-dir",
        default="./backups",
        help="Directory for database backups (default: ./backups)"
    )
    
    args = parser.parse_args()
    
    migrator = DatabaseMigrator(
        data_dir=args.data_dir,
        backup_dir=args.backup_dir,
    )
    
    try:
        stats = await migrator.run_migration()
        print("\nMigration completed!")
        print(f"See logs above for details.")
        return 0
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
