# PostgreSQL Setup Guide

## Quick Start with Docker

### 1. Start PostgreSQL Container

```bash
docker run -d \
  --name pa-postgres \
  -e POSTGRES_USER=pa_user \
  -e POSTGRES_PASSWORD=secure_password_here \
  -e POSTGRES_DB=personal_assistant \
  -p 5432:5432 \
  -v pa_postgres_data:/var/lib/postgresql/data \
  postgres:15
```

### 2. Verify Connection

```bash
# Install psql if needed (PostgreSQL client)
# macOS: brew install postgresql@15
# Ubuntu: sudo apt-get install postgresql-client

psql -h localhost -U pa_user -d personal_assistant -c "SELECT 1"
```

Expected output:
```
 ?column?
----------
        1
(1 row)
```

## Using Docker Compose

Create `docker-compose.yml`:

```yaml
version: '3.8'
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: pa_user
      POSTGRES_PASSWORD: secure_password_here
      POSTGRES_DB: personal_assistant
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U pa_user"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
    driver: local
```

Then start with:
```bash
docker-compose up -d
docker-compose logs postgres
```

## Environment Configuration

### .env File

```env
# Database Configuration
DB_TYPE=postgresql

# PostgreSQL Connection
DB_POSTGRESQL_HOST=localhost
DB_POSTGRESQL_PORT=5432
DB_POSTGRESQL_USER=pa_user
DB_POSTGRESQL_PASSWORD=secure_password_here
DB_POSTGRESQL_DATABASE=personal_assistant
DB_POSTGRESQL_SSL=prefer

# Connection Pool
DB_POSTGRESQL_POOL_SIZE=10
DB_POSTGRESQL_MAX_OVERFLOW=20

# Dual-write mode (optional, for testing migration)
DB_DUAL_WRITE=false
```

## Schema Initialization

### Automatic (Recommended)

The Personal Assistant will automatically create all tables on first connection:

```bash
poetry run python -c "
import asyncio
from src.store.knowledge import UnifiedKnowledgeStore
from src.config.database import DatabaseConfig

config = DatabaseConfig.from_env()
store = UnifiedKnowledgeStore(db_type=config.db_type, **config.to_connection_kwargs())
asyncio.run(store.initialize())
print('✓ Schema created')
"
```

### Manual

If you need to create the schema manually:

```bash
poetry run python scripts/init_postgres_schema.py \
  --host localhost \
  --port 5432 \
  --user pa_user \
  --password secure_password_here \
  --database personal_assistant
```

## Testing Connection

### From Python

```python
import asyncio
from src.store.db_connection import PostgreSQLConnection

async def test():
    conn = PostgreSQLConnection(
        host="localhost",
        port=5432,
        user="pa_user",
        password="secure_password_here",
        database="personal_assistant"
    )
    await conn.initialize()
    row = await conn.fetchone("SELECT 1 as test")
    print(f"✓ Connected: {row}")
    await conn.close()

asyncio.run(test())
```

### From CLI

```bash
psql -h localhost -U pa_user -d personal_assistant
```

## Troubleshooting

### Connection Refused
```
Error: could not connect to server: Connection refused
```

**Solution:** Ensure PostgreSQL is running and listening on port 5432
```bash
# Check if container is running
docker ps | grep pa-postgres

# Check container logs
docker logs pa-postgres

# Restart if needed
docker restart pa-postgres
```

### Authentication Failed
```
Error: FATAL: password authentication failed for user "pa_user"
```

**Solution:** Verify credentials in `.env` match Docker environment
```bash
# Check .env
grep DB_POSTGRESQL_PASSWORD .env

# Verify Docker environment (if using Docker)
docker inspect pa-postgres | grep -A 10 POSTGRES
```

### SSL/TLS Certificate Errors
```
Error: SSL certificate problem
```

**Solution:** Set `DB_POSTGRESQL_SSL=disable` temporarily for local development
```env
DB_POSTGRESQL_SSL=disable  # or 'prefer' for production
```

### Too Many Connections
```
Error: FATAL: too many connections for role "pa_user"
```

**Solution:** Increase connection limit or pool size
```env
DB_POSTGRESQL_POOL_SIZE=5   # Reduce from 10
DB_POSTGRESQL_MAX_OVERFLOW=10  # Or use connection pooler like pgBouncer
```

## Backup & Restore

### Backup PostgreSQL

```bash
# Dump entire database
pg_dump -h localhost -U pa_user -d personal_assistant > backup.sql

# Compressed backup (recommended)
pg_dump -h localhost -U pa_user -d personal_assistant | gzip > backup.sql.gz

# With Docker
docker exec pa-postgres pg_dump -U pa_user personal_assistant | gzip > backup.sql.gz
```

### Restore PostgreSQL

```bash
# From SQL file
psql -h localhost -U pa_user -d personal_assistant < backup.sql

# From compressed file
gunzip -c backup.sql.gz | psql -h localhost -U pa_user -d personal_assistant

# With Docker
docker exec -i pa-postgres psql -U pa_user personal_assistant < backup.sql
```

## Performance Tuning

### Create Indexes

```sql
-- Citation queries
CREATE INDEX IF NOT EXISTS idx_citations_year ON citations(year);
CREATE INDEX IF NOT EXISTS idx_citations_doi ON citations(doi);
CREATE INDEX IF NOT EXISTS idx_citations_arxiv_id ON citations(arxiv_id);

-- Concept queries
CREATE INDEX IF NOT EXISTS idx_concepts_label ON concepts(label);
CREATE INDEX IF NOT EXISTS idx_concepts_category ON concepts(category);

-- Interest queries
CREATE INDEX IF NOT EXISTS idx_interests_label ON interests(label);
CREATE INDEX IF NOT EXISTS idx_interests_strength ON interests(strength);

-- Research log
CREATE INDEX IF NOT EXISTS idx_interest_research_log_topic ON interest_research_log(topic);
CREATE INDEX IF NOT EXISTS idx_interest_research_log_last_researched_at ON interest_research_log(last_researched_at);

-- Full-text search (optional, for future)
CREATE INDEX IF NOT EXISTS idx_citations_title_fulltext ON citations USING GIN (to_tsvector('english', title));
```

### Run ANALYZE

```sql
ANALYZE;
```

This updates table statistics for query planner optimization.

### Monitor Performance

```sql
-- Slow queries
SELECT query, calls, mean_time, max_time
FROM pg_stat_statements
ORDER BY mean_time DESC
LIMIT 10;

-- Table sizes
SELECT schemaname, tablename, pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- Connection count
SELECT usename, count(*) FROM pg_stat_activity GROUP BY usename;
```

## Production Deployment

For production, consider:

1. **Use a Managed Service** (e.g., AWS RDS, Google Cloud SQL, Azure Database)
   - Automatic backups and replication
   - High availability (failover)
   - Managed patching

2. **Connection Pooling** with PgBouncer
   ```yaml
   pgbouncer:
     image: edoburu/pgbouncer
     environment:
       PGBOUNCER_POOL_SIZE: 10
       PGBOUNCER_MIN_POOL_SIZE: 1
     ports:
       - "6432:6432"
   ```

3. **Enable SSL/TLS**
   ```env
   DB_POSTGRESQL_SSL=require
   ```

4. **Enable Query Logging**
   ```sql
   ALTER SYSTEM SET log_statement = 'all';
   ALTER SYSTEM SET log_duration = 'on';
   SELECT pg_reload_conf();
   ```

5. **Set WAL Archiving** for point-in-time recovery
   ```sql
   ALTER SYSTEM SET wal_level = replica;
   ALTER SYSTEM SET archive_mode = on;
   SELECT pg_reload_conf();
   ```

## References

- [PostgreSQL Official Documentation](https://www.postgresql.org/docs/)
- [asyncpg Documentation](https://magicstack.github.io/asyncpg/)
- [PostgreSQL Docker Image](https://hub.docker.com/_/postgres)
