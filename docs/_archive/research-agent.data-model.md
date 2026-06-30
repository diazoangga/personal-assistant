---
title: "Research Agent — Data Model Design"
created: 2026-06-23
updated: 2026-06-23
version: 1.0.0
status: Design (pre-implementation)
tags: [research-agent, data-model, citation-graph, knowledge-graph, schema]
related:
  - research-agent.implementation-plan.md
  - SYSTEM_DOCUMENTATION.md
  - impl/06-research-agent.md
  - database_migration.md
reference:
  - https://api.semanticscholar.org/api-docs/graph
  - https://arxiv.org/help/api
  - https://www.litmaps.com/
---

> Whenever this file changes, bump `updated` and add a changelog entry.

# Research Agent — Data Model Design

This is the **first** of two documents. It fixes the data model the Research Agent
writes into; [research-agent.implementation-plan.md](research-agent.implementation-plan.md)
then builds the agent on top of it. **Design the schema first, then refine the agent.**

---

## 1. Goals (what the data model must support)

| # | Requirement | Mechanism in this design |
|---|---|---|
| G1 | Research results are **persisted** in the database. | All output upserted into the canonical `UnifiedKnowledgeStore` (`./data/knowledge.db`). |
| G2 | The agent can **search and follow citations**. | Semantic Scholar references/cited-by populate `citation_relationships` (`cites` edges). |
| G3 | A **knowledge graph** of the whole topic (concepts + typed relations). | `concepts` + `concept_relationships`. |
| G4 | A **citation graph** like litmaps.com (papers + cites edges), with rich nodes carrying title, authors, abstract, conclusion, notes, … | extended `citations` table + `citation_relationships`. |
| G5 | Both graphs are **always updated on every research run** — incremental, idempotent, no duplicate nodes. | content-addressed IDs + `UPSERT` + novelty dedup. |
| G6 | Research is **linked to interests**, so researching an interest reuses prior knowledge. | `interest_citation_links`, `interest_concept_links`, `research_runs`. |

---

## 2. Decisions locked before this design

1. **Canonical store, not `graph.py`.** Everything lands in `UnifiedKnowledgeStore`
   (`src/store/knowledge.py`). The parallel `CitationGraph`/`KnowledgeGraph` classes in
   `src/store/graph.py` are **deprecated** — they keep separate tables
   (`citation_nodes`, `concept_nodes`, `relation_edges`) that nothing in the live engine
   uses. The implementation plan removes them.
2. **Citation source = Semantic Scholar** (Graph API), with **arXiv supplementary** for
   fresh preprints. arXiv alone gives no citation edges, so it cannot build a litmaps-style
   graph; Semantic Scholar provides `references`, `citations`, `tldr`, `citationCount`.
3. **`conclusion` and `notes` are LLM-synthesized** from the abstract + TLDR, not parsed
   from full-text PDFs. `notes` is also the home for later agent/user annotations.

---

## 3. Entity model (conceptual)

```
                 ┌────────────┐  interest_citation_links   ┌────────────┐
                 │  interest  │───────────────────────────▶│  citation  │ (paper node)
                 └────────────┘                            └────────────┘
                   │      │                                   │   ▲   │
 interest_concept_links   │                  citation_concept_links  │ citation_relationships
                   ▼      │ research_runs                     ▼   │   │ (cites: paper→paper)
              ┌────────────┐ (provenance + summary)      ┌────────────┐
              │  concept   │◀───────────────────────────▶│  concept   │
              └────────────┘   concept_relationships      └────────────┘
                (knowledge graph: typed concept↔concept edges)
```

- **Citation graph** = `citations` (nodes) + `citation_relationships` (directed `cites` edges). *Litmaps-style.*
- **Knowledge graph** = `concepts` (nodes) + `concept_relationships` (typed edges). *Whole-topic concept map.*
- **Bridges** = `citation_concept_links` (a paper discusses a concept) and the two
  `interest_*` link tables (an interest owns papers and concepts).
- **Provenance** = `research_runs` records each run, its deltas, and the summary, so prior
  research is discoverable and reusable.

---

## 4. Schema changes

All changes are additive against the existing schema in
[`src/store/knowledge.py`](../src/store/knowledge.py). Existing columns keep their names;
new columns are added via idempotent `ALTER TABLE ... ADD COLUMN` guarded by a
`PRAGMA table_info` check (see [§8 Migration](#8-migration)).

### 4.1 `citations` — extended (citation-graph node)

Current columns: `id, arxiv_id, doi, title, abstract, authors, published_date, journal,
categories, citation_count, created_at`. **Add:**

| New column | Type | Source | Purpose |
|---|---|---|---|
| `semantic_scholar_id` | TEXT UNIQUE | Semantic Scholar `paperId` | Primary key for the citation graph; lets references/citations resolve to existing nodes. |
| `url` | TEXT | S2 `url` / arXiv abs link | Open the paper. |
| `tldr` | TEXT | S2 `tldr.text` | One-line machine summary (seed for synthesis). |
| `conclusion` | TEXT | **LLM-synthesized** | 1–2 sentence takeaway (G4). |
| `notes` | TEXT (JSON) | **LLM + later user/agent** | Structured notes: `{key_contributions, methods, limitations, user_notes}`. |
| `year` | INTEGER | S2 `year` | Cheap axis for litmaps time-layout (derived from `published_date` if missing). |
| `venue` | TEXT | S2 `venue` | Alias-level field alongside legacy `journal`. |
| `reference_count` | INTEGER | S2 `referenceCount` | Out-degree hint. |
| `influential_citation_count` | INTEGER | S2 `influentialCitationCount` | Edge/node weighting in the graph. |
| `source` | TEXT | `semantic_scholar` \| `arxiv` \| `openalex` | Provenance / authority ranking. |
| `last_researched_at` | TEXT | run timestamp | Reuse + staleness checks. |
| `embedding_cached` | INTEGER (0/1) | KB step | Whether abstract is embedded in Qdrant. |

> `authors` and `categories` stay JSON-encoded TEXT, as today. `citation_count` is retained
> (live count from S2). The node therefore carries **title, authors, abstract, conclusion,
> notes** plus discovery/ranking metadata — exactly the litmaps card.

### 4.2 `citation_relationships` — now populated (citation-graph edge)

Table already exists (`source_id, target_id, relationship_type`) but is **never written**
today. This design makes it the citation-graph edge store.

- `relationship_type` vocabulary: **`cites`** (source paper → target paper it references).
  Reserved for future: `extends`, `contradicts`.
- Add `UNIQUE(source_id, target_id, relationship_type)` so re-research is idempotent.
- Add index `idx_citation_rel_source(source_id)` and `idx_citation_rel_target(target_id)`
  for fast forward/backward traversal (litmaps walks both directions).
- Edges are **directed**: `A cites B`. "Cited-by" is the reverse lookup, not a second row.

### 4.3 `concepts` — minor enrichment (knowledge-graph node)

Current: `id, label, description, category, created_at`. **Add:**

| New column | Type | Purpose |
|---|---|---|
| `mention_count` | INTEGER DEFAULT 0 | How many papers/runs mentioned it — node salience for ranking/layout. |
| `first_seen_run_id` | TEXT | Provenance: which run introduced it. |

`category` keeps the closed vocabulary already used by entity extraction:
`concept / method / model / task / dataset / metric / framework`.

### 4.4 `concept_relationships` — unchanged (knowledge-graph edge)

Already `UNIQUE(source_id, target_id, relation_type)` with `weight` and `evidence`.
Relation vocabulary (closed): `uses, extends, competes_with, evaluated_on, part_of,
related_to`. `weight` accumulates across runs (reinforced, not duplicated).

### 4.5 `interest_citation_links` — NEW (interest → paper)

The direct edge that satisfies G6 ("research linked to interests"). Lets the agent answer
*"what do I already have on this interest?"* in one query, and lets a future UI list an
interest's papers.

```sql
CREATE TABLE IF NOT EXISTS interest_citation_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interest_id TEXT NOT NULL,
    citation_id TEXT NOT NULL,
    relevance REAL DEFAULT 0.5,         -- topical match score at link time
    discovered_run_id TEXT,             -- which research run added it
    created_at TEXT NOT NULL,
    FOREIGN KEY (interest_id) REFERENCES interests(id) ON DELETE CASCADE,
    FOREIGN KEY (citation_id) REFERENCES citations(id) ON DELETE CASCADE,
    UNIQUE(interest_id, citation_id)
);
CREATE INDEX IF NOT EXISTS idx_interest_citation ON interest_citation_links(interest_id);
```

> `interest_concept_links` already exists for interest → concept; this table is its
> citation counterpart. Together they make an interest a **front door** into both graphs.

### 4.6 `research_runs` — NEW (provenance + reuse)

One row per research invocation. Records what was done, the deltas, and the cited summary —
the basis for reuse (G6) and for the daemon's cooldown semantics.

```sql
CREATE TABLE IF NOT EXISTS research_runs (
    id TEXT PRIMARY KEY,                -- uuid
    topic TEXT NOT NULL,
    interest_id TEXT,                   -- nullable; set when triggered for an interest
    trigger_source TEXT NOT NULL,       -- 'manual' | 'interest' | 'brainstorm'
    depth TEXT NOT NULL,                -- 'shallow' | 'normal' | 'deep'
    status TEXT NOT NULL,               -- 'running' | 'completed' | 'failed'
    papers_found INTEGER DEFAULT 0,
    papers_new INTEGER DEFAULT 0,       -- nodes added this run (delta)
    concepts_extracted INTEGER DEFAULT 0,
    concepts_new INTEGER DEFAULT 0,
    relationships_found INTEGER DEFAULT 0,
    summary TEXT,                       -- LLM "what's new", cited
    error TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (interest_id) REFERENCES interests(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_research_runs_topic ON research_runs(topic);
CREATE INDEX IF NOT EXISTS idx_research_runs_interest ON research_runs(interest_id);
```

> The existing `interest_research_log` (topic → `last_researched_at`) stays as the
> lightweight **cooldown** record the Interest Agent already uses. `research_runs` is the
> richer **history**. They are complementary, not a merge (keeps the cooldown decoupling
> noted in SYSTEM_DOCUMENTATION §11.6).

---

## 5. Identity & idempotency (how G5 holds)

Re-researching a topic must **update**, never duplicate. Identity rules:

- **Citation ID** — `compute_citation_id(paper)` picks the first available stable key:
  `doi` → `arxiv_id` → `semantic_scholar_id` → `sha256(normalized_title)[:16]`. The same
  paper from two sources collapses to one node. Cross-source IDs (`arxiv_id`,
  `semantic_scholar_id`, `doi`) are stored as UNIQUE columns so a later source backfills
  fields on the existing row.
- **Concept ID** — unchanged `compute_concept_id(label, category)` (content-addressed).
- **Edges** — both edge tables have a UNIQUE triple; second sighting bumps
  `weight` / counts instead of inserting.
- **Counters** — `citation_count`, `mention_count`, `concept_relationships.weight` are
  refreshed/accumulated on upsert, so the graph gets *richer* per run, not bigger with
  dupes.

**Novelty gate.** Before chasing a paper's citations the agent calls `is_known(citation_id)`;
known papers are re-weighted but their frontier isn't re-expanded, which is what stops a
deep run from re-walking the whole graph (the D4 "keep chasing?" decision in the impl plan).

---

## 6. Store API to add (`UnifiedKnowledgeStore`)

Grouped by concern. Signatures are the contract the agent codes against.

**Citation graph**
```python
async def upsert_citation(self, citation: dict) -> str            # extended; returns citation_id
async def add_citation_edge(self, source_id, target_id, rel="cites") -> None
async def get_citation_edges(self, citation_id) -> list[dict]      # both directions
async def is_known_citation(self, citation_id) -> bool
async def citation_subgraph(self, seed_ids, max_depth=2) -> tuple[list, list]  # litmaps export
async def update_citation_notes(self, citation_id, notes: dict) -> None        # conclusion/notes/user notes
```

**Interest linkage (G6 / reuse)**
```python
async def link_interest_to_citation(self, interest_id, citation_id, relevance=0.5, run_id=None) -> None
async def get_citations_for_interest(self, interest_id) -> list[dict]
async def get_existing_research(self, topic, interest_id=None) -> dict
    # → {runs: [...], citations: [...], concepts: [...]} — what we already know, for reuse
```

**Provenance**
```python
async def start_research_run(self, run: dict) -> str
async def finish_research_run(self, run_id, **deltas_and_summary) -> None
async def get_research_runs(self, topic=None, interest_id=None, limit=20) -> list[dict]
```

Existing, reused as-is: `upsert_concept`, `add_concept_relationship`,
`link_citation_to_concept`, `link_interest_to_concept`, `relevant_subgraphs`
(knowledge-graph traversal), `find_concepts_by_label`.

---

## 7. Reads that make the graphs useful

| Query | Method | Backs |
|---|---|---|
| Litmaps citation graph for a topic/interest | `citation_subgraph(seed_ids, depth)` seeded from `get_citations_for_interest` | `pa graph --kind citation` / future viz |
| Knowledge graph for a topic/interest | `relevant_subgraphs(interests=[label], max_depth)` | `pa graph --kind knowledge` |
| "What do I already know about X?" (reuse) | `get_existing_research(topic, interest_id)` | Agent step 1; avoids redundant fetches |
| Papers behind a concept | `get_linked_citations_for_concept(concept_id)` (exists) | Brainstorm/Opportunity grounding |
| Research history of an interest | `get_research_runs(interest_id=...)` | `pa interests`, digests |

Both subgraph methods return `(nodes, edges)` as plain dict lists — directly serializable to
JSON for a future graph frontend (vis-network / litmaps-like canvas). No viz is built now;
the **shape** is fixed here so the frontend is additive later.

---

## 8. Migration

`knowledge.db` already exists in the field, so new columns/tables must be applied without
dropping data. `_create_tables()` gains an idempotent migration helper:

```python
async def _add_column_if_missing(self, table, column, ddl):
    cols = {r["name"] for r in await self.execute_query(f"PRAGMA table_info({table})")}
    if column not in cols:
        await self._db.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
```

- New tables use `CREATE TABLE IF NOT EXISTS` (already the pattern).
- New columns on `citations` / `concepts` use the helper above (SQLite `ADD COLUMN` is cheap,
  fills existing rows with NULL/default).
- `citation_relationships` UNIQUE constraint can't be added by `ALTER`; since the table is
  currently empty in practice, the migration recreates it (`CREATE ... _new`, copy, swap) —
  documented in [database_migration.md](database_migration.md).
- Indexes are `CREATE INDEX IF NOT EXISTS`.

No destructive change; a fresh DB and an existing DB converge to the same schema.

---

## 9. What this explicitly does NOT cover

- **Graph visualization / frontend** — out of scope; §7 fixes the export shape so it's additive.
- **Full-text PDF parsing** — `conclusion`/`notes` are LLM-synthesized from abstract+TLDR
  (locked decision). Full-text is a later enhancement that would only *backfill* the same fields.
- **OpenAlex connector** — listed as a future fallback source; not in the first build.
- **Vector/embedding details** — `embedding_cached` flags KB membership; Qdrant mechanics live
  in [03-vector-db-and-storage.md](impl/03-vector-db-and-storage.md).

---

## Changelog
- **1.0.0** (2026-06-23): Initial data-model design. Extends `citations`, populates
  `citation_relationships` as the citation graph, enriches `concepts`, adds
  `interest_citation_links` and `research_runs`, deprecates `src/store/graph.py`. Locks
  Semantic Scholar (primary) + arXiv (supplementary) and LLM-synthesized conclusion/notes.
