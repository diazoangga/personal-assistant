# PostgreSQL Migration Checklist

Use this checklist to track migration progress through all phases.

## Phase 0: Preparation (Before Migration)

### Week Before
- [ ] Read [DATABASE_MIGRATION_SQLITE_TO_POSTGRES.md](./DATABASE_MIGRATION_SQLITE_TO_POSTGRES.md)
- [ ] Read [POSTGRES_SETUP.md](./POSTGRES_SETUP.md)
- [ ] Notify team: "Migration window scheduled for [DATE TIME UTC]"
- [ ] Back up current SQLite database
  ```bash
  cp ./data/knowledge.db ./data/knowledge.db.backup.$(date +%Y%m%d)
  ```

### Day Before
- [ ] Verify PostgreSQL dependencies installed
  ```bash
  poetry add asyncpg
  ```
- [ ] Test PostgreSQL Docker image locally
  ```bash
  docker pull postgres:15-alpine
  ```
- [ ] Review current database size
  ```bash
  ls -lh ./data/knowledge.db
  ```

## Phase 1: Setup (2 hours)

### PostgreSQL Container
- [ ] Start PostgreSQL container
  ```bash
  docker-compose up -d postgres
  ```
- [ ] Wait for health check to pass (logs: "database system is ready")
  ```bash
  docker logs -f personal-assistant-postgres
  ```
- [ ] Verify connection from host
  ```bash
  psql -h localhost -U pa_user -d personal_assistant -c "SELECT 1"
  ```

### Environment Configuration
- [ ] Copy `.env.example` to `.env` if not exists
  ```bash
  cp .env.example .env
  ```
- [ ] Update `.env` with PostgreSQL credentials
  ```env
  DB_TYPE=postgresql
  DB_POSTGRESQL_HOST=localhost
  DB_POSTGRESQL_PORT=5432
  DB_POSTGRESQL_USER=pa_user
  DB_POSTGRESQL_PASSWORD=<password>
  DB_POSTGRESQL_DATABASE=personal_assistant
  DB_POSTGRESQL_SSL=prefer
  ```
- [ ] Verify .env is in .gitignore (should not commit)

### Code Updates
- [ ] Confirm `pyproject.toml` has asyncpg dependency
- [ ] Confirm new files exist:
  - [ ] `src/store/db_connection.py`
  - [ ] `src/config/database.py`
  - [ ] `src/config/__init__.py`
- [ ] Run linting
  ```bash
  poetry run black src/ && poetry run ruff check src/
  ```

## Phase 2: Data Migration (1 hour)

### Pre-Migration Validation
- [ ] Verify SQLite database integrity
  ```bash
  sqlite3 ./data/knowledge.db "PRAGMA integrity_check;"
  ```
  Expected: "ok"
- [ ] Check table count
  ```bash
  sqlite3 ./data/knowledge.db "SELECT COUNT(*) FROM sqlite_master WHERE type='table';"
  ```
  Expected: ~15 tables
- [ ] Check row counts for each table
  ```bash
  poetry run python scripts/validate_sqlite.py
  ```

### Data Migration
- [ ] Run migration script with verification
  ```bash
  poetry run python scripts/migrate_to_postgres.py \
    --from-sqlite ./data/knowledge.db \
    --to-postgres postgresql://pa_user:password@localhost/personal_assistant \
    --mode full \
    --verify
  ```
- [ ] Expected output: "✓ All X tables migrated. Row counts match."
- [ ] Confirm no errors in migration logs

### Post-Migration Validation
- [ ] Verify PostgreSQL row counts match SQLite
  ```bash
  poetry run python scripts/validate_postgres.py
  ```
- [ ] Check PostgreSQL tables created
  ```bash
  psql -h localhost -U pa_user -d personal_assistant -c "\dt"
  ```
  Expected: ~15 tables listed
- [ ] Verify sequences reset (for auto-increment IDs)
  ```bash
  psql -h localhost -U pa_user -d personal_assistant -c "\ds"
  ```

## Phase 3: Testing (30 minutes)

### Unit Tests
- [ ] Run full test suite
  ```bash
  poetry run pytest tests/ -v
  ```
- [ ] Expected: All tests pass
- [ ] If failures: Check logs and fix issues before proceeding

### Integration Tests
- [ ] Test CLI commands work with PostgreSQL
  ```bash
  poetry run pa interests
  poetry run pa ask "test query"
  poetry run pa brainstorm
  ```
- [ ] Verify output matches expected format
- [ ] Check for any error messages

### Data Integrity Tests
- [ ] Verify interests are readable
  ```bash
  psql -h localhost -U pa_user -d personal_assistant -c "SELECT COUNT(*) FROM interests;"
  ```
- [ ] Verify citations are readable
  ```bash
  psql -h localhost -U pa_user -d personal_assistant -c "SELECT COUNT(*) FROM citations;"
  ```
- [ ] Verify concepts are readable
  ```bash
  psql -h localhost -U pa_user -d personal_assistant -c "SELECT COUNT(*) FROM concepts;"
  ```

## Phase 4: Cutover (30 minutes)

### Pre-Cutover Checklist
- [ ] All tests passing ✓
- [ ] Data migration complete ✓
- [ ] Backup created ✓
- [ ] Team notified ✓

### Enable PostgreSQL Primary
- [ ] Update production `.env` (if separate from dev)
  ```bash
  export DB_TYPE=postgresql
  ```
- [ ] Stop daemon (if running)
  ```bash
  poetry run pa daemon stop
  ```
- [ ] Restart daemon with PostgreSQL
  ```bash
  poetry run pa daemon start
  ```
- [ ] Check daemon logs for errors
  ```bash
  tail -f ./data/daemon.log
  ```

### Verification
- [ ] Daemon starts without errors
- [ ] CLI works: `pa interests`
- [ ] New signals can be processed
- [ ] Research agent can run
- [ ] Brainstorming agent works

### Disable SQLite (Optional, after 24h validation)
- [ ] Wait 24 hours to confirm no issues
- [ ] Remove SQLite fallback code (if implemented)
- [ ] Archive SQLite backup
  ```bash
  gsutil cp ./data/knowledge.db.backup gs://backups/
  ```

## Phase 5: Post-Migration (1 week)

### Day 1 (Cutover Day)
- [ ] Monitor application logs every hour
- [ ] Check PostgreSQL logs for errors
  ```bash
  docker logs -f personal-assistant-postgres
  ```
- [ ] Verify no data corruption
- [ ] Test all major features work

### Days 2-3
- [ ] Monitor for any performance issues
- [ ] Check database size hasn't grown unexpectedly
  ```bash
  psql -h localhost -U pa_user -d personal_assistant -c "
    SELECT pg_size_pretty(pg_database_size('personal_assistant'));
  "
  ```
- [ ] Review slow query logs
  ```bash
  psql -h localhost -U pa_user -d personal_assistant -c "
    SELECT query, calls, mean_time FROM pg_stat_statements 
    ORDER BY mean_time DESC LIMIT 10;
  "
  ```

### Days 4-7
- [ ] Run full test suite again
- [ ] Perform data consistency check
- [ ] Archive old SQLite database

### One Week Later
- [ ] Remove "dual-write" code (if any remains)
- [ ] Update documentation to reference PostgreSQL only
- [ ] Schedule team knowledge share session

## Troubleshooting Guide

### Issue: Connection Refused

**Error:**
```
psycopg2.OperationalError: could not connect to server: Connection refused
```

**Fix:**
1. Verify container is running: `docker ps | grep postgres`
2. Check port 5432 is listening: `netstat -an | grep 5432`
3. Restart container: `docker-compose restart postgres`

### Issue: Migration Timeout

**Error:**
```
asyncio.TimeoutError: Operation timed out
```

**Fix:**
1. Increase timeout in migration script
2. Check network connectivity: `ping localhost`
3. Check PostgreSQL logs: `docker logs postgres`

### Issue: Duplicate Key Errors

**Error:**
```
ERROR: duplicate key value violates unique constraint
```

**Fix:**
1. Reset sequences: `poetry run python scripts/migrate_to_postgres.py --reset-sequences`
2. Check for duplicate data in SQLite before migration

### Issue: Row Count Mismatch

**Error:**
```
✗ Table X: 1000 → 950 rows
```

**Fix:**
1. Investigate missing rows
2. Re-run migration with `--mode incremental`
3. Check for constraint violations in PostgreSQL

### Rollback to SQLite

If critical issues occur:

1. Stop daemon
   ```bash
   poetry run pa daemon stop
   ```
2. Revert .env
   ```bash
   export DB_TYPE=sqlite
   ```
3. Restart daemon
   ```bash
   poetry run pa daemon start
   ```
4. Report issue in #critical-incidents channel
5. Schedule post-mortem

## Success Criteria

✅ All tests pass on PostgreSQL  
✅ Data row counts match between SQLite and PostgreSQL  
✅ CLI commands work without changes  
✅ Daemon processes signals normally  
✅ No performance regression  
✅ Brainstorming agent works with new DB  
✅ Backup exists for rollback  

## Sign-Off

When all phases complete:

- [ ] Migration lead approval
- [ ] Test results documented
- [ ] Team notified: "Migration complete, PostgreSQL active"
- [ ] Post-migration review scheduled for [DATE]

---

## Quick Reference Commands

```bash
# Check PostgreSQL status
docker ps | grep postgres
docker logs -f personal-assistant-postgres

# Connect to database
psql -h localhost -U pa_user -d personal_assistant

# Show all tables
psql -h localhost -U pa_user -d personal_assistant -c "\dt"

# Backup PostgreSQL
pg_dump -h localhost -U pa_user -d personal_assistant > backup.sql

# Run tests
poetry run pytest tests/ -v

# Check application
poetry run pa interests
```

---

**Migration Date:** [FILL IN]  
**Migration Lead:** [FILL IN]  
**Stakeholders Notified:** [FILL IN]  
**Status:** Not Started → In Progress → Complete
