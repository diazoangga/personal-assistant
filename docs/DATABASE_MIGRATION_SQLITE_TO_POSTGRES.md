# SQLite to PostgreSQL Migration Guide

## Overview

This document describes the complete migration from SQLite (`knowledge.db`) to PostgreSQL for the Personal Assistant system. The migration is fully reversible and includes zero-downtime deployment strategies.

**Timeline:** Migration window: 2-4 hours  
**Risk Level:** Medium (data-intensive operation)  
**Rollback Plan:** Automatic via connection string revert

---

## Architecture & Benefits

### Current State (SQLite)
- **Storage:** File-based (`./data/knowledge.db`)
- **Concurrency:** Row-level locking, single writer
- **Scalability:** Limited to single machine
- **Backup:** File copy
- **Ops:** Minimal; no server setup needed

### Post-Migration (PostgreSQL)
- **Storage:** Dedicated server (local or cloud)
- **Concurrency:** MVCC (Multi-Version Concurrency Control) — true concurrent writes
- **Scalability:** Horizontal scaling via read replicas, partitioning
- **Backup:** Native WAL (Write-Ahead Logging), point-in-time recovery
- **Ops:** Managed or self-hosted PostgreSQL 14+

### Trade-offs
| Aspect | SQLite | PostgreSQL |
|--------|--------|-----------|
| Setup Complexity | Trivial | Medium |
| Server Dependency | None | Required |
| Write Concurrency | Single | Multiple |
| Query Performance | Good for <100M rows | Excellent for large datasets |
| Operational Complexity | Minimal | Medium (but worth it at scale) |

---

## Migration Strategy

### Phase 1: Preparation
1. **Provision PostgreSQL** (local Docker or managed service)
2. **Add asyncpg dependency** to `pyproject.toml`
3. **Dual-write database layer** (abstract DB connection)
4. **Schema validation** (DDL equivalence check)

### Phase 2: Dual-Write (Dark Launch)
1. Writes go to both SQLite and PostgreSQL
2. Validation: Reads from PostgreSQL, compare to SQLite
3. Run for 24–48 hours to catch edge cases
4. Monitor for discrepancies

### Phase 3: Cutover
1. **Read traffic → PostgreSQL** (stop reading from SQLite)
2. **Write traffic → PostgreSQL only** (stop writing to SQLite)
3. **Verify** all queries work, no regressions
4. **Archive** SQLite backup (`knowledge.db.backup`)

### Phase 4: Cleanup
1. Remove SQLite connection code (after 1-week validation period)
2. Archive old `knowledge.db` to long-term storage
3. Document in CHANGELOG

---

## Database Schema Mapping

### Table Structure & Type Changes

#### Key Differences
| SQLite Type | PostgreSQL Type | Notes |
|------------|-----------------|-------|
| TEXT | TEXT | Unchanged |
| REAL | DOUBLE PRECISION | Unchanged |
| INTEGER | INTEGER / BIGINT | Autoincrement differs |
| BLOB | BYTEA | Binary data; encoding/decoding differs |
| AUTOINCREMENT | SERIAL / BIGSERIAL | Must reset sequence after import |
| PRAGMA foreign_keys | Session-level constraint | Always enabled in PostgreSQL |

### Schema Validation Checklist

```python
# Validation queries (run before cutover)
SELECT * FROM information_schema.tables 
WHERE table_schema = 'public' 
ORDER BY table_name;

SELECT table_name, column_name, data_type 
FROM information_schema.columns 
WHERE table_schema = 'public' 
ORDER BY table_name, ordinal_position;

SELECT constraint_name, constraint_type 
FROM information_schema.table_constraints 
WHERE table_schema = 'public';
```

---

## Implementation Plan

### Step 1: Update Dependencies

**File:** `pyproject.toml`

Add PostgreSQL driver:
```toml
asyncpg = "^0.29.0"  # Async PostgreSQL client
psycopg = {version = "^3.1.0", extras = ["binary"]}  # Alternative for production
```

### Step 2: Create Database Abstraction

**New File:** `src/store/db_connection.py`

Abstract connection interface that works with both SQLite and PostgreSQL:
```python
class DatabaseConnection:
    async def initialize(self) -> None: ...
    async def execute(self, query: str, params: tuple = ()) -> Any: ...
    async def fetchall(self, query: str, params: tuple = ()) -> list: ...
    async def fetchone(self, query: str, params: tuple = ()) -> Optional[dict]: ...
    async def commit(self) -> None: ...
    async def close(self) -> None: ...
```

### Step 3: Update Configuration

**File:** `.env.example`

```env
# Database Configuration
DB_TYPE=postgresql  # or sqlite
DB_SQLITE_PATH=./data/knowledge.db

# PostgreSQL
DB_POSTGRESQL_HOST=localhost
DB_POSTGRESQL_PORT=5432
DB_POSTGRESQL_USER=pa_user
DB_POSTGRESQL_PASSWORD=secure_password
DB_POSTGRESQL_DATABASE=personal_assistant
DB_POSTGRESQL_SSL=prefer  # require, prefer, disable
DB_POSTGRESQL_POOL_SIZE=10
DB_POSTGRESQL_MAX_OVERFLOW=20
```

### Step 4: Update UnifiedKnowledgeStore

**File:** `src/store/knowledge.py`

- Replace `aiosqlite.Connection` with factory pattern
- Add PostgreSQL-specific schema handling
- Remove SQLite PRAGMAs
- Add automatic sequence reset for autoincrement columns

### Step 5: Data Migration Script

**New File:** `scripts/migrate_to_postgres.py`

```bash
# Usage
python scripts/migrate_to_postgres.py \
  --from-sqlite ./data/knowledge.db \
  --to-postgres postgresql://user:pass@localhost/personal_assistant \
  --mode full|incremental \
  --verify
```

Features:
- Full copy of all tables and data
- Preserve autoincrement sequences
- Idempotent (safe to run multiple times)
- Validation mode: compare row counts, checksums
- Rollback capability (transaction-based)

### Step 6: Testing Strategy

**Existing Tests:** Update to run against both backends
```python
@pytest.fixture(params=["sqlite", "postgresql"])
async def knowledge_store(request):
    if request.param == "sqlite":
        yield await create_sqlite_store()
    else:
        yield await create_postgresql_store()
```

---

## Deployment Procedure

### Prerequisites
```bash
# 1. PostgreSQL running locally or remotely
docker run -d \
  --name postgres \
  -e POSTGRES_USER=pa_user \
  -e POSTGRES_PASSWORD=secure_password \
  -e POSTGRES_DB=personal_assistant \
  -p 5432:5432 \
  postgres:15

# 2. Create .env with PostgreSQL connection
cp .env.example .env
# Edit .env with PostgreSQL credentials
```

### Step-by-Step Deployment

#### 1. Validation (Pre-Migration)
```bash
# Verify current SQLite database integrity
poetry run python scripts/validate_sqlite.py

# Check table schemas
poetry run python scripts/check_schema.py
```

#### 2. Dual-Write Setup
```bash
# Update code to write to both databases
git checkout feat/dual-write  # Switch to dual-write branch
poetry install  # Get new asyncpg dependency
poetry run pytest tests/  # Run full test suite

# Start daemon in dual-write mode
export DB_DUAL_WRITE=true
poetry run pa daemon start
```

#### 3. Initial Data Migration
```bash
# Full migration from SQLite → PostgreSQL
poetry run python scripts/migrate_to_postgres.py \
  --from-sqlite ./data/knowledge.db \
  --to-postgres postgresql://pa_user:password@localhost/personal_assistant \
  --mode full \
  --verify

# Output: "✓ All 15 tables migrated. Row counts match."
```

#### 4. Cutover (No-Downtime)
```bash
# 1. Stop writes to SQLite
export DB_PRIMARY=postgresql
export DB_DUAL_WRITE=false

# 2. Perform final sync (incremental migration of any new data)
poetry run python scripts/migrate_to_postgres.py \
  --from-sqlite ./data/knowledge.db \
  --to-postgres postgresql://pa_user:password@localhost/personal_assistant \
  --mode incremental

# 3. Health check
poetry run pytest tests/test_store.py::test_postgres_integration -v

# 4. Switch production config
sed -i 's/DB_TYPE=sqlite/DB_TYPE=postgresql/g' .env.production
```

#### 5. Validation & Cleanup
```bash
# 1. Run smoke tests
pa interests          # List interests
pa ask "test query"   # Ask something

# 2. Archive SQLite backup
cp ./data/knowledge.db ./data/knowledge.db.backup.$(date +%Y%m%d_%H%M%S)

# 3. Remove old SQLite code (after 1-week validation)
git checkout feat/remove-sqlite-code
```

---

## Rollback Procedure

If critical issues emerge:

```bash
# 1. Revert to SQLite in config
export DB_TYPE=sqlite
export DB_SQLITE_PATH=./data/knowledge.db

# 2. Restart daemon
poetry run pa daemon restart

# 3. Root cause analysis
# - Check PostgreSQL logs: `docker logs postgres`
# - Compare data: `scripts/validate_postgresql.py`
# - File issue in tracking system
```

**Note:** PostgreSQL data is preserved; rollback is non-destructive.

---

## Configuration Reference

### SQLite (Current)
```env
DB_TYPE=sqlite
DB_SQLITE_PATH=./data/knowledge.db
```

### PostgreSQL (New)
```env
DB_TYPE=postgresql
DB_POSTGRESQL_HOST=localhost
DB_POSTGRESQL_PORT=5432
DB_POSTGRESQL_USER=pa_user
DB_POSTGRESQL_PASSWORD=<secure_password>
DB_POSTGRESQL_DATABASE=personal_assistant
DB_POSTGRESQL_SSL=prefer
DB_POSTGRESQL_POOL_SIZE=10
```

### Dual-Write (Temporary)
```env
DB_TYPE=postgresql            # Primary
DB_DUAL_WRITE=true           # Enable dual-write
DB_SQLITE_PATH=./data/knowledge.db  # Secondary (validation)
```

---

## Performance Expectations

### Query Performance
| Operation | SQLite | PostgreSQL | Note |
|-----------|--------|-----------|------|
| Insert 1000 rows | ~500ms | ~400ms | Indexed columns |
| Select 10k rows | ~100ms | ~80ms | With indexes |
| Join concepts ↔ citations | ~2s | ~200ms | PostgreSQL indexes win |
| Full-text search | N/A | ~50ms | Requires GIN index |

### Storage
| Component | SQLite | PostgreSQL | Note |
|-----------|--------|-----------|------|
| knowledge.db file | ~50MB | Tables + WAL: ~60MB | WAL overhead |
| Backup size | ~5MB compressed | ~6MB compressed | Minimal difference |

---

## Monitoring & Observability

### Health Checks

```bash
# PostgreSQL connectivity
poetry run python -c "
import asyncio
from src.store.knowledge import UnifiedKnowledgeStore
store = UnifiedKnowledgeStore()
asyncio.run(store.initialize())
print('✓ Connected to PostgreSQL')
"

# Data validation
poetry run python scripts/validate_postgresql.py

# Query monitoring
psql -U pa_user -d personal_assistant -c "
SELECT query, calls, mean_time 
FROM pg_stat_statements 
ORDER BY mean_time DESC LIMIT 10;
"
```

### Logging

Enable query logging:
```bash
# In PostgreSQL
ALTER DATABASE personal_assistant SET log_statement = 'all';
ALTER DATABASE personal_assistant SET log_duration = 'on';
```

---

## Common Issues & Solutions

### Issue 1: Connection Pool Exhaustion
**Symptom:** `FATAL: too many connections`

**Solution:**
```env
DB_POSTGRESQL_POOL_SIZE=20  # Increase pool size
```

### Issue 2: Autoincrement Sequences Out of Sync
**Symptom:** Duplicate key errors on INSERT

**Solution:**
```python
# Reset sequences after bulk insert
await store._reset_sequences()  # Internal method
```

### Issue 3: Timezone Mismatches
**Symptom:** Timestamp comparisons fail

**Solution:**
```env
# Use UTC consistently
DB_POSTGRESQL_TIMEZONE=UTC
```

### Issue 4: BLOB → BYTEA Encoding
**Symptom:** Embedding data is corrupted

**Solution:**
- SQLite: BLOB stored as raw bytes
- PostgreSQL: Use `encoding='latin1'` when reading/writing

---

## Timeline Estimate

| Phase | Task | Estimated Time |
|-------|------|-----------------|
| 1 | Setup PostgreSQL, update deps | 15 min |
| 2 | Implement dual-write layer | 2 hours |
| 3 | Data migration & validation | 30 min |
| 4 | Smoke tests & verification | 1 hour |
| 5 | Production cutover | 30 min |
| **Total** | | **4.5 hours** |

---

## Success Criteria

✅ All existing tests pass on PostgreSQL  
✅ Data integrity: Row counts and checksums match  
✅ No performance regression on common queries  
✅ Daemon starts and processes signals normally  
✅ CLI commands (pa ask, pa interests, pa brainstorm) work  
✅ No data loss during migration  

---

## Post-Migration

### Optimization (Optional)
```sql
-- Add indexes for common queries
CREATE INDEX idx_citations_year ON citations(year);
CREATE INDEX idx_concepts_label ON concepts(label);
CREATE INDEX idx_interest_research_log_topic ON interest_research_log(topic);

-- Enable query analysis
ANALYZE;
```

### Archival
```bash
# Move SQLite backup to cold storage
gsutil cp ./data/knowledge.db.backup gs://personal-assistant-backups/
rm ./data/knowledge.db*
```

---

## References

- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [asyncpg GitHub](https://github.com/MagicStack/asyncpg)
- [SQLite to PostgreSQL Migration Best Practices](https://wiki.postgresql.org/wiki/Migration)
