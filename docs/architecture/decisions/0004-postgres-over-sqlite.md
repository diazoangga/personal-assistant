# ADR-0004: PostgreSQL backend alongside SQLite

**Status:** Accepted · **Date:** 2026-06

## Context

Development started on SQLite (`knowledge.db`) — zero setup, perfect for a local tool. As
the store grew (concurrent daemon + API writers, larger graphs) we wanted a production
backend with real concurrency and a server deployment story, without forking the data
layer or rewriting every query.

## Decision

Make the relational backend selectable at runtime via `DB_TYPE` (`sqlite` | `postgresql`),
resolved by `config/database.py::DatabaseConfig.from_env()`. A `DBConnection` abstraction
(`store/db_connection.py`) hides the driver behind `execute`/`fetchone`/`fetchall`/`commit`,
and **rewrites `?` placeholders to `$n`** for the PostgreSQL driver so the same SQL strings
in `UnifiedKnowledgeStore` work on both. Schema DDL is shared; column adds use
`_add_column_if_missing` for forward migrations.

## Consequences

- **+** One codebase, two backends; dev stays on frictionless SQLite, prod runs Postgres.
- **+** Query authors write `?`-style SQL once; the connection layer adapts it.
- **−** The lowest-common-denominator SQL forgoes Postgres-specific features.
- **−** Two backends to test; placeholder rewriting and type quirks (booleans, JSON) are a
  recurring source of subtle bugs.
- Migration details and operational guidance live in
  [storage/postgres.md](../../storage/postgres.md).
