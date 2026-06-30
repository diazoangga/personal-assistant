# ADR-0002: One Unified Knowledge Store

**Status:** Accepted · **Date:** 2026-06 (retroactive)

## Context

Early on, state was fragmented across separate databases — `memory.db` (interests),
`citations.db`, `concepts.db`. Cross-cutting reads (e.g. "papers and concepts linked to
this interest") meant joining across files, and every agent had to know which DB held what.

## Decision

Collapse everything into a single relational database fronted by one class,
`UnifiedKnowledgeStore` (`store/knowledge.py`): the interest model, citation graph, concept
graph, the cross-reference link tables that join them, research-run records, conversation
history, and high-quality knowledge entries all live in one schema. The class is fully
async and the only relational data-access path for the agents and the web API.

## Consequences

- **+** Cross-graph queries (`relevant_subgraphs`, `get_existing_research`) are ordinary
  SQL joins, not multi-DB orchestration.
- **+** One `initialize()` creates the whole schema; one connection to manage.
- **+** Backend is swappable (SQLite ↔ PostgreSQL) at one seam — see
  [ADR-0004](0004-postgres-over-sqlite.md).
- **−** The schema is large (~20 tables) and the class is big (~1.4k LOC); it is a natural
  bottleneck/God-object risk.
- **−** Legacy `store/memory.py` still holds some interest tables; the consolidation into
  `knowledge.py` is not fully finished.
