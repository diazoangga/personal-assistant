---
title: "Implementation: Vector DB & Storage"
created: 2026-06-20
updated: 2026-06-21
version: 3.0.0
status: Draft
tags: [implementation, storage, vector-db, rag, memory, interest-graph, knowledge-graph]
changelog:
  - version: 1.0.0
    date: 2026-06-20
    changes: "Initial two-store design for the SDLC builder"
  - version: 2.0.0
    date: 2026-06-21
    changes: >-
      Updated for the cognitive engine. Memory now stores the user profile,
      interest graph, opportunities, signal log, and feedback (replacing
      build/architect/developer artifacts). Chunk provenance uses `connector`.
      Retrieval pipeline (hybrid + rerank + semantic chunking) retained.
  - version: 3.0.0
    date: 2026-06-21
    changes: >-
      Added the Graph Store (plans.md v4.0.0): citation graph + knowledge graph
      node/edge tables, written by the new Research Agent. Knowledge Base is
      now filled only by the Research Agent (not a generic ingestion pipeline);
      `Chunk.connector` narrowed to research-source connectors.
related:
  - ../personal-assistant.plans.md
  - 04-daily-research-agent.md
  - 06-research-agent.md
---

> Whenever this documentation file changes, update the `updated` field and append a new entry to `changelog` describing the revision.

# Implementation: Vector DB & Storage

Three stores, three jobs. The **Knowledge Base** (vector DB) compresses the
Research Agent's findings into the few relevant paragraphs an agent needs. The
**Graph Store** (SQLite) holds the citation graph and knowledge graph the Research
Agent builds. **Persistent Memory** (SQLite) holds the **user model** — profile,
interest graph, opportunities, feedback — plus job state, across commands,
interfaces, and restarts.

> On local hardware small models live or die by context quality. The retrieval
> layer is the difference between a usable local assistant and one that hallucinates.

---

## 1. Knowledge Base (Vector DB)

Filled exclusively by the **Research Agent** ([06-research-agent.md](06-research-agent.md))
— triggered by an Interest Agent classification, not a generic scheduled pull. The
activity sensing pipeline ([04](04-daily-research-agent.md)) never writes here; it
only feeds the Interest Agent's signal log in Persistent Memory (§2).

### Backend choice

| Backend | Pick it when |
|---------|--------------|
| **Qdrant** (Docker) | You want a purpose-built engine with first-class hybrid (dense + sparse) search and payload filtering. **Default.** |
| **pgvector** (Postgres) | You already want Postgres for Memory too and prefer one DB with SQL + `tsvector` for the keyword half. |

The `store/vector.py` client wraps whichever backend behind one interface.

```python
# src/store/vector.py
class KnowledgeBase:
    async def upsert(self, chunks: list[Chunk]) -> None: ...
    async def search(self, query: str, k: int = 8) -> list[Hit]: ...   # hybrid + rerank
    async def prune(self, older_than_days: int) -> int: ...
```

### Hybrid retrieval + rerank
Pure vector search is losing ground; **hybrid (dense + sparse/BM25) with a rerank
pass** gives the best quality-to-cost ratio.

```
query
  ├─ dense:  embed(query) → vector top-N        (semantic)
  ├─ sparse: BM25 / tsvector top-N              (exact terms, names, APIs)
  ├─ fuse:   Reciprocal Rank Fusion → candidates
  └─ rerank: cross-encoder (local, e.g. bge-reranker) → top-k
```

The sparse half matters: technical research is full of exact tokens (library names,
APIs) that dense embeddings blur. This is the **Hybrid Retrieval skill** used by
Brainstorm and the Opportunity Agent.

### Chunking: semantic, not fixed-size
Start a new chunk when consecutive-sentence similarity drops below a threshold, so a
chunk holds one coherent idea; fall back to a max-token cap.

```python
def semantic_chunks(text: str, *, sim_threshold=0.6, max_tokens=512) -> list[str]: ...
```

### Provenance & citations
Every chunk carries metadata so any answer/recommendation is traceable — provenance
is the core promise ("why this?"), not a nice-to-have.

```python
@dataclass
class Chunk:
    id: str                 # content hash (idempotent upsert / dedup key)
    text: str
    embedding: list[float]
    source_url: str | None
    connector: str          # "arxiv" | "github_research" | "medium" | "news" — research connectors only (see 06)
    topic: str              # interest/classification it matched
    ingested_at: str        # ISO date (aging/pruning)
    quality: float          # research-time score (source authority, recency, topic-match)
```

`Ask`/Brainstorm answers and Opportunity proposals cite `source_url` per claim. `id`
is a hash of normalized text → re-ingest is a no-op (dedup + idempotency in one).

### Embeddings (local)
From Ollama (`nomic-embed-text` / `bge-m3`). Same model for ingestion and query —
never mix embedding models within a collection.

### Aging & pruning
A scheduled `prune(older_than_days=90)` drops stale entries; keep anything pinned by
a saved opportunity. Run in the off-peak window.

---

## 2. Persistent Memory (SQLite) — the user model

SQLite is enough for a single-user local assistant (Postgres is a config flip). It
holds the user model and everything that must survive a restart.

> **Memory is a Tool, not an agent (D4).** This store + the Memory Retrieval skill
> are what an earlier draft mistakenly called a "Memory Agent". A store doesn't
> reason. Write-policy ("don't blindly overwrite") is enforced by the Meta Agent.

### Schema (illustrative)

```sql
-- long-term user profile (one row, or key/value facets)
CREATE TABLE profile (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);

-- interest graph: nodes (topics) + edges (relationships), maintained by Interest Agent
CREATE TABLE interest_nodes (
  id TEXT PRIMARY KEY, name TEXT, parent_id TEXT,
  strength REAL,                 -- current interest strength
  state TEXT,                    -- emerging | active | abandoned
  first_seen TEXT, last_seen TEXT
);
CREATE TABLE interest_edges (src TEXT, dst TEXT, relation TEXT, weight REAL,
  PRIMARY KEY (src, dst, relation));

-- raw activity signal log, feeds the Interest Agent; aged out by policy
-- (research content does NOT land here — it goes straight to the Knowledge Base
--  and Graph Store via the Research Agent; see 06-research-agent.md)
CREATE TABLE signals (
  id TEXT PRIMARY KEY, connector TEXT,
  title TEXT, url TEXT, occurred_at TEXT, topic TEXT
);

-- self-modification proposals (D6) — Meta Agent drafts, human approves/rejects/edits
CREATE TABLE proposals (
  id TEXT PRIMARY KEY, target TEXT,        -- "skill:<name>" | "prompt:<name>" | "tool:<name>"
  diff TEXT, evidence TEXT, rationale TEXT,
  state TEXT,                              -- pending | approved | rejected | edited_then_approved
  created_at TEXT, reviewed_at TEXT
);

-- opportunities produced by the Opportunity Agent / saved from Brainstorm
CREATE TABLE opportunities (
  id TEXT PRIMARY KEY, kind TEXT,        -- project | research | learning | startup
  title TEXT, body TEXT,
  provenance TEXT,                       -- JSON: interest signals + KB source ids ("why this")
  score REAL, state TEXT,                -- proposed | saved | dismissed
  created_at TEXT
);

-- feedback record powering the self-improvement loop
CREATE TABLE feedback (
  id INTEGER PRIMARY KEY, ref TEXT, agent TEXT,
  verdict TEXT,                          -- accept | reject | correct | save | dismiss
  note TEXT, created_at TEXT
);

-- job + session state (powers `pa status`, survives restart)
CREATE TABLE jobs (
  job_id TEXT PRIMARY KEY, kind TEXT, user TEXT, state TEXT,
  created_at TEXT, updated_at TEXT
);

-- ephemeral brainstorm sessions (chat history; separate from long-term memory)
CREATE TABLE sessions (session_id TEXT PRIMARY KEY, user TEXT, history TEXT, updated_at TEXT);

-- user preferences and tracked classifications
CREATE TABLE prefs  (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE topics (name TEXT PRIMARY KEY, keywords TEXT);

-- episodic memory: compact run traces for self-improvement
CREATE TABLE run_traces (job_id TEXT PRIMARY KEY, summary TEXT, outcome TEXT, lessons TEXT, created_at TEXT);
```

### Access layer

```python
# src/store/memory.py
class Memory:
    # profile + interests
    def upsert_profile(self, key, value) -> None: ...
    def top_interests(self, n=10) -> list[InterestNode]: ...
    def apply_interest_delta(self, delta) -> None: ...
    # signals + opportunities + feedback
    def log_signal(self, s: Signal) -> None: ...
    def save_opportunity(self, o: Opportunity) -> None: ...
    def set_opportunity_state(self, id, state) -> None: ...
    def record_feedback(self, fb: Feedback) -> None: ...
    # jobs + sessions + traces
    def upsert_job(self, job) -> None: ...
    def get_session(self, sid) -> Session | None: ...
    def record_trace(self, trace) -> None: ...
```

> **Why separate stores:** vector DBs are bad at transactional point-reads ("what's
> the strength of interest X?"), graph traversal ("what cites this paper, two hops
> out?") wants edge tables, and SQLite is bad at semantic search. Each does the one
> thing it's good at. The engine is the only component that touches all three.

---

## 3. Graph Store — citation graph + knowledge graph

Written exclusively by the **Research Agent** ([06-research-agent.md](06-research-agent.md));
read by the Opportunity Agent (synthesis input) and the Brainstorming Agent (citing
a graph node in an answer). Modeled as node/edge tables — the same shape already
used for the interest graph above, generalized with a `graph` column so both graph
types share one pair of tables rather than forking schema per graph kind.

```sql
-- nodes: papers (citation graph) or concepts/entities (knowledge graph)
CREATE TABLE graph_nodes (
  id TEXT PRIMARY KEY,
  graph TEXT,              -- "citation" | "knowledge"
  kind TEXT,               -- "paper" | "repo" | "article" | "concept" | "entity"
  label TEXT, source_url TEXT,
  metadata TEXT,           -- JSON: authors/year for papers, etc.
  novelty_score REAL,      -- similarity-to-existing-graph at insert time (Research Agent's novelty decision)
  first_seen TEXT, last_seen TEXT
);

-- edges: "cites" (citation graph) or typed relations (knowledge graph)
CREATE TABLE graph_edges (
  src TEXT, dst TEXT,
  graph TEXT,              -- "citation" | "knowledge"
  relation TEXT,           -- "cites" | "uses" | "extends" | "competes_with" | ...
  weight REAL,
  created_at TEXT,
  PRIMARY KEY (src, dst, graph, relation)
);
```

```python
# src/store/graph.py
class GraphStore:
    async def apply(self, delta: GraphDelta) -> None: ...               # upsert nodes/edges
    async def is_novel(self, candidate, *, graph: str, threshold: float) -> bool: ...
    async def relevant_subgraphs(self, interests, focus=None) -> list[Subgraph]: ...
    async def citation_chain(self, paper_id: str, hops: int = 2) -> Subgraph: ...
```

> **One pair of tables, two graphs, by design.** A citation graph and a knowledge
> graph are structurally the same thing (nodes + typed edges); forking into
> `citation_nodes`/`knowledge_nodes` would just duplicate the access layer. The
> `graph` column is the only thing that varies; query by it, don't fork the schema.

---

## 4. The Knowledge ↔ Memory ↔ Graph Boundary

| Question | Store |
|----------|-------|
| "Find research relevant to *local LLM quantization*." | Knowledge Base (semantic) |
| "What am I most interested in right now?" | Memory `interest_nodes` (point read) |
| "Why did you recommend this?" | Memory `opportunities.provenance` (→ cites KB + graph nodes) |
| "Has this article already been researched?" | Knowledge Base (`id` hash) **and** Graph Store (`is_novel`) |
| "What does this paper cite, two hops out?" | Graph Store `citation_chain` |
| "How does concept X relate to concept Y across my research?" | Graph Store (knowledge graph) |
| "What did I dismiss last week?" | Memory `opportunities` / `feedback` |
| "What's my default preference for X?" | Memory `prefs` |
| "What self-modification did Meta propose, and is it approved?" | Memory `proposals` |

---

## 5. `Ask` & Brainstorm Inquiry — Agentic RAG with citations

`Ask` (one-shot) and Brainstorm inquiry turns run the retrieval pipeline above, then
optionally go **multi-hop** (Query Reformulation skill): if the first retrieval
doesn't cover the question, reformulate and retrieve again (bounded to N hops) before
answering. **Strict grounding:** every claim carries its `source_url`; if the KB
doesn't cover it, say so rather than guess. Single-hop is the default; reserve
multi-hop for genuinely compositional questions to keep local latency sane.

---

## 6. docker-compose (sketch)

```yaml
services:
  qdrant:
    image: qdrant/qdrant:latest
    ports: ["6333:6333"]
    volumes: ["./.data/qdrant:/qdrant/storage"]
  # OR, if vector_backend = pgvector:
  postgres:
    image: pgvector/pgvector:pg16
    environment: { POSTGRES_PASSWORD: pa }
    ports: ["5432:5432"]
    volumes: ["./.data/pg:/var/lib/postgresql/data"]
```

SQLite needs no service — it's a file at `settings.storage.memory_db`.

---

## 7. Testing

- **Retrieval quality:** fixture corpus + (query → expected doc) pairs; assert
  expected doc in top-k. Guards chunking/embedding regressions.
- **Idempotency:** research the same paper/article twice → one chunk set, no
  duplicate graph nodes, only a `last_seen`/weight update.
- **Interest graph:** apply a signal delta; assert strength/decay and state
  transitions (emerging → active → abandoned).
- **Graph traversal:** fixture citation chain → assert `citation_chain` returns the
  expected hops and stops at the requested depth.
- **Provenance:** save an opportunity; assert `provenance` resolves to real signal +
  KB source + graph node ids.
- **Self-modification gate:** assert a `proposals` row never transitions to
  `approved` except via the reviewer-facing path (no code path writes `approved`
  directly).

---

## Related
- [04-daily-research-agent.md](04-daily-research-agent.md) — fills the activity signal log only
- [06-research-agent.md](06-research-agent.md) — fills the Knowledge Base + Graph Store
- [05-meta-agent-and-skills.md](05-meta-agent-and-skills.md) — consumes retrieval + memory; Meta's `proposals` workflow
- [../personal-assistant.implementation.md](../personal-assistant.implementation.md)
