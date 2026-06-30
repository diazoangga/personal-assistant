# Relational Backend: SQLite ↔ PostgreSQL

The relational store runs on SQLite (dev) or PostgreSQL (prod), chosen at runtime. One set
of SQL strings serves both. Rationale in
[ADR-0004](../architecture/decisions/0004-postgres-over-sqlite.md).

## Selecting the backend

`config/database.py::DatabaseConfig.from_env()` reads `DB_TYPE` (`sqlite` | `postgresql`)
and the per-backend env vars, then `main_engine.py` constructs the store with
`to_connection_kwargs()`:

```python
db_config = DatabaseConfig.from_env()
store = UnifiedKnowledgeStore(db_type=db_config.db_type, **db_config.to_connection_kwargs())
await store.initialize()
```

### Environment variables

| Var | Default | Notes |
|---|---|---|
| `DB_TYPE` | `sqlite` | `sqlite` or `postgresql` |
| `DB_SQLITE_PATH` | `./data/knowledge.db` | SQLite file |
| `DB_POSTGRESQL_HOST` | `localhost` | |
| `DB_POSTGRESQL_PORT` | `5432` | |
| `DB_POSTGRESQL_USER` | `pa_user` | |
| `DB_POSTGRESQL_PASSWORD` | `""` | |
| `DB_POSTGRESQL_DATABASE` | `personal_assistant` | |
| `DB_POSTGRESQL_SSL` | `prefer` | |
| `DB_POSTGRESQL_POOL_SIZE` / `_MAX_OVERFLOW` | `10` / `20` | connection pool |
| `DB_DUAL_WRITE` | `false` | temporary dual-write during migration |

## The connection abstraction

`store/db_connection.py` defines `DBConnection` (ABC) with
`execute / fetchone / fetchall / commit / begin_transaction / rollback / close`, and two
implementations: `SQLiteConnection` and the PostgreSQL wrapper. `UnifiedKnowledgeStore`
only ever talks to this interface.

**Placeholder rewriting is the key trick:** all SQL in the store uses `?` placeholders
(SQLite style). The PostgreSQL connection rewrites `?` → `$1, $2, …` before executing, so
the same query strings run on both backends. Rows come back as dicts either way.

## Running Postgres locally

```bash
docker compose up -d        # if a postgres service is defined in docker-compose.yml
# then point the app at it:
export DB_TYPE=postgresql
export DB_POSTGRESQL_PASSWORD=...   # plus host/user/database as needed
```

`store.initialize()` creates the schema on either backend (idempotent
`CREATE TABLE IF NOT EXISTS`), so there is no separate migration step for a fresh DB.
Forward column changes are handled by `_add_column_if_missing`.

## Migrating existing SQLite data

Migrating an existing `knowledge.db` into Postgres is a data copy (schema is created by
`initialize()`); `DB_DUAL_WRITE=true` exists to write both backends during a transition
window. Operational migration scripts live under `scripts/`.

## Gotchas

- **Booleans / JSON** — SQLite is permissive; Postgres is strict. Values stored as JSON
  text (`authors`, `categories`, `metadata`, `raw_data`) are serialised by the store.
- **`commit()` is explicit** — `execute_query` does not commit; writers that need
  durability call `store._db.execute(...)` then `store._db.commit()` (the API's feedback
  write does exactly this).
- **Test on both** — placeholder rewriting and type coercion are the usual bug sources.

---

> **Source of truth:** `src/config/database.py`, `src/store/db_connection.py`,
> `src/store/knowledge.py`, `scripts/`.
