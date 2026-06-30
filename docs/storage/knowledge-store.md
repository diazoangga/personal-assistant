# Unified Knowledge Store

One async class, `UnifiedKnowledgeStore` (`store/knowledge.py`), over one relational
database holds everything: the interest model, the citation graph, the concept graph, the
link tables that join them, research runs, conversations, and knowledge entries. Backend is
SQLite (dev) or PostgreSQL (prod), selected by `DB_TYPE` — see
[postgres.md](postgres.md) and [ADR-0002](../architecture/decisions/0002-unified-knowledge-store.md).

## Schema map

```
                interests ──< interest_signal_evidence
                    │ ▲          (evidence → decay)
                    │ └── interest_embeddings
        ┌───────────┼───────────────┬───────────────────┐
        ▼           ▼               ▼                   ▼
 interest_citation interest_concept research_runs   opportunities
   _links            _links            │             │   └─ opportunity_interest_links
        │               │              │
        ▼               ▼              ▼
    citations ──< citation_concept_links >── concepts
        │  ▲                                   │
        │  └── citation_relationships          └── concept_relationships
        ▼        (cites / references)              (typed, weighted)
   (papers)

 conversation_sessions ──< conversation_turns
        │
        └──< knowledge_entries (auto-saved high-quality Q&A)
   user_stats · user_profile · activity_log
```

## Tables by domain

**Interest model**
| Table | Key columns |
|---|---|
| `interests` | `id, label, strength, created_at, updated_at, last_active` |
| `interest_signal_evidence` | `signal_id, topic, confidence, timestamp` — `UNIQUE(signal_id, topic)`; the decay source |
| `interest_embeddings` | `interest_id, embedding (BLOB), model_version` |
| `interest_research_log` | `topic UNIQUE, last_researched_at` — research cooldown |

**Citation graph**
| Table | Key columns |
|---|---|
| `citations` | `id, title, abstract, authors(JSON), doi, arxiv_id, semantic_scholar_id, year, venue, tldr, conclusion, notes, citation_count, source, …` |
| `citation_relationships` | `source_id, target_id, relationship_type` — `UNIQUE(source,target,type)` |

**Concept graph**
| Table | Key columns |
|---|---|
| `concepts` | `id, label, description, category, mention_count, first_seen_run_id` |
| `concept_relationships` | `source_id, target_id, relation_type, weight` |

**Cross-reference (the joins that make it a knowledge graph)**
| Table | Joins |
|---|---|
| `interest_concept_links` | interest ↔ concept (`link_type`, `confidence`) |
| `citation_concept_links` | citation ↔ concept (`relation_type`, `evidence_text`) |
| `interest_citation_links` | interest ↔ citation (`relevance`, `discovered_run_id`) |

**Research runs** — `research_runs(id, topic, interest_id, trigger_source, depth, status,
papers_found, papers_new, concepts_extracted, concepts_new, relationships_found, summary,
error, started_at, completed_at)`.

**Conversation & knowledge**
| Table | Key columns |
|---|---|
| `conversation_sessions` | `id, user_id, question_count, metadata` |
| `conversation_turns` | `session_id, turn_number, role, content, timestamp` |
| `knowledge_entries` | `id, question, answer, quality_score, user_id, embedded, metadata` |
| `user_stats` / `user_profile` / `activity_log` | counters, prefs, daemon activity feed |

## Content-addressed IDs & idempotency

`compute_citation_id(citation)` and `compute_concept_id(label, category)` hash identifying
fields, so `upsert_citation` / `upsert_concept` deduplicate across runs. Edge tables carry
`UNIQUE` constraints so re-linking is a no-op. This is what makes re-researching a topic
*enrich* rather than *duplicate*.

## Key method groups

- **Interests:** `upsert_interest`, `get_interests(min_strength)`, `add_classified_signal`,
  `get_strength`, `should_research`, `mark_researched`, `get_interest_embeddings`.
- **Graphs:** `upsert_citation`, `add_citation_edge`, `upsert_concept`,
  `add_concept_relationship`, the `link_*`/`get_linked_*` family, `relevant_subgraphs`,
  `citation_subgraph`.
- **Research:** `get_existing_research`, `start_research_run`, `finish_research_run`,
  `get_research_runs`.
- **Conversation/knowledge:** `get_or_create_session`, `add_conversation_turn`,
  `get_conversation_history`, `store_knowledge_entry`, `get_knowledge_entries`,
  `search_knowledge_entries`, `get_stats`.

## Initialization & migration

`initialize()` runs `_create_tables` (idempotent `CREATE TABLE IF NOT EXISTS` + indexes).
Forward schema changes use `_add_column_if_missing(table, column, ddl)`; the
`citation_relationships` table has a bespoke `_migrate_citation_relationships` to add its
`UNIQUE` edge constraint to pre-existing databases.

## Access pattern note

The web API's `queries.py` reaches `store._db.fetchall/fetchone/execute` directly for a few
dashboard reads. SQL uses `?` placeholders everywhere; the Postgres connection wrapper
rewrites them to `$n` ([postgres.md](postgres.md)).

---

> **Source of truth:** `src/store/knowledge.py`, `src/store/db_connection.py`.
