# Database Migration Guide

## Overview

This guide explains how to migrate from the old multi-database architecture to the new unified `knowledge.db` architecture.

## Architecture Changes

### Before (Old Architecture)
- `memory.db` - User interests, profile, opportunities
- `citations.db` - Research papers and citations  
- `concepts.db` - Concept nodes and relationships
- **Problem**: Data silos, complex cross-referencing

### After (New Architecture)
- `knowledge.db` - Single unified database with all data
- **Benefits**: 
  - Simplified queries across all knowledge layers
  - Built-in cross-references (interests ↔ concepts ↔ citations)
  - Easier backups and maintenance
  - Better support for hybrid classification

## Migration Steps

### 1. Backup Your Data (Automatic)

The migration script automatically creates backups of all existing databases in `./backups/` with timestamps:
```
backups/
  memory_20260621_143022.db
  citations_20260621_143022.db
  concepts_20260621_143022.db
```

### 2. Run Migration Script

```bash
# From project root
python scripts/migrate_to_unified_db.py
```

Or with custom paths:
```bash
python scripts/migrate_to_unified_db.py --data-dir ./data --backup-dir ./backups
```

### 3. What Gets Migrated

The script migrates:
- ✅ All interests with strengths and metadata
- ✅ All concepts and relationships
- ✅ All citations and relationships
- ✅ User profile data
- ✅ Opportunities
- ✅ Activity logs
- ✅ Auto-links interests to concepts (exact + substring matches)

### 4. Post-Migration

After migration completes:
1. Verify the new `knowledge.db` exists in `./data/`
2. Update your config if needed (already updated in `config/settings.toml`)
3. Test the application
4. Keep backups for at least one week before deleting

## Rollback Procedure

If you need to rollback to the old architecture:

1. Stop the application
2. Delete `knowledge.db`
3. Restore backups:
   ```bash
   cp backups/memory_*.db data/memory.db
   cp backups/citations_*.db data/citations.db
   cp backups/concepts_*.db data/concepts.db
   ```
4. Revert code changes (if needed)

## New Schema Features

### Cross-Reference Tables

**interest_concept_links**
- Links user interests to knowledge graph concepts
- Supports multiple link types: `exact_match`, `substring_match`, `manual`
- Confidence scores for automatic links

**citation_concept_links**  
- Links research papers to concepts they discuss
- Includes evidence text showing why linked

**interest_signal_evidence**
- Stores classified activity signals
- Used for computing decayed interest strengths

**interest_research_log**
- Tracks when topics were last researched
- Prevents duplicate research via cooldown periods

### Embedding Cache

**interest_embeddings**
- Caches embeddings for fast semantic similarity matching
- Enables hybrid classification (semantic + LLM fallback)
- Reduces LLM API calls by ~70%

## Testing

Run the test suite to verify migration success:

```bash
python tests/test_unified_store.py
```

This tests:
- Interest CRUD operations
- Concept management
- Citation storage
- Linking between entities
- Embedding cache
- Signal evidence tracking
- Research cooldown logic

## Configuration Changes

Updated `config/settings.toml`:

```toml
[storage]
# Old (separate DBs)
memory_db = "./data/memory.db"
citation_graph_db = "./data/citations.db"
knowledge_graph_db = "./data/concepts.db"

# New (unified)
knowledge_db = "./data/knowledge.db"
```

## Performance Notes

- Indexes created on frequently queried columns
- Foreign keys enabled for referential integrity
- Embedding lookups use binary storage (efficient)
- Cross-reference queries optimized with indexes

## Troubleshooting

### Migration Fails

Check logs for specific errors. Common issues:
- **Database locked**: Close any applications using the DB files
- **Missing tables**: Ensure old databases have correct schema
- **Disk space**: Ensure enough space for backups + new database

### Application Won't Start After Migration

1. Check `config/settings.toml` points to `knowledge.db`
2. Verify `main_engine.py` uses `UnifiedKnowledgeStore`
3. Check application logs for initialization errors

## Next Steps

After successful migration:
1. Consider running embedding backfill for all interests (if not done during migration)
2. Review auto-created interest-concept links
3. Manually link important citations to concepts
4. Monitor LLM API usage reduction from hybrid classification

---

For questions or issues, check the project documentation or create an issue.
