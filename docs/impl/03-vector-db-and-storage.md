---
title: "Implementation: Vector DB & Storage"
created: 2026-06-20
updated: 2026-06-20
version: 1.0.0
status: Draft
tags: [implementation, storage, vector-db, rag, memory]
related:
  - ../personal-assistant.plans.md
  - 04-daily-research-agent.md
---

> Whenever this documentation file changes, update the `updated` field and append a new entry to `changelog` describing the revision.

# Implementation: Vector DB & Storage

Two stores, two jobs. The **Knowledge Base** (vector DB) protects the LLM context
window by compressing accumulated research into the few relevant paragraphs an
agent needs. **Persistent Memory** (SQLite) keeps execution continuity — job
state, preferences, tasks — across commands, interfaces, and restarts.

> Why this matters most on local hardware: small models live or die by context
> quality. The retrieval layer is the difference between a usable local assistant
> and one that hallucinates.

---

## 1. Knowledge Base (Vector DB)

### Backend choice

| Backend | Pick it when |
|---------|--------------|
| **Qdrant** (Docker) | You want a purpose-built vector engine with first-class hybrid (dense + sparse) search and payload filtering. **Default recommendation.** |
| **pgvector** (Postgres in Docker) | You already want Postgres for Persistent Memory too and prefer one database with SQL + `tsvector` for the keyword half. |

Both run in `docker-compose.yml`. The `knowledge/vector.py` client wraps whichever
backend behind one interface so the rest of the system doesn't care.

```python
# pa/knowledge/vector.py
class KnowledgeBase:
    async def upsert(self, chunks: list[Chunk]) -> None: ...
    async def search(self, query: str, k: int = 8) -> list[Hit]: ...   # hybrid + rerank
    async def prune(self, older_than_days: int) -> int: ...
```

### Hybrid retrieval + rerank (2026 default)

Pure vector search is losing ground; **hybrid retrieval (dense vector + sparse
keyword/BM25) with a rerank pass** is the fastest-growing pattern and gives the
best quality-to-cost ratio. Pipeline:

```
query
  ├─ dense:  embed(query) → vector top-N        (semantic)
  ├─ sparse: BM25 / tsvector top-N              (exact terms, names, APIs)
  ├─ fuse:   Reciprocal Rank Fusion → candidate set
  └─ rerank: cross-encoder (local, e.g. bge-reranker) → top-k
```

Keeping the sparse half matters here: technical research is full of exact tokens
(library names, error strings, API params) that dense embeddings blur. RRF needs
no tuning; the rerank pass is what sharpens the final top-k handed to the model.

### Chunking: semantic, not fixed-size

Chunking is the #1 silent failure point. Use **semantic chunking**: start a new
chunk when cosine similarity between consecutive sentences drops below a threshold,
so a chunk holds one coherent idea. Fall back to a max token cap to bound size.

```python
# pa/research/ingest.py (chunking step)
def semantic_chunks(text: str, *, sim_threshold=0.6, max_tokens=512) -> list[str]:
    # split to sentences → embed → cut where similarity drops or max_tokens hit
    ...
```

### Provenance & citations

Every chunk carries metadata so any answer is traceable — citations are a 2026
baseline expectation, not a nice-to-have.

```python
@dataclass
class Chunk:
    id: str                 # content hash (idempotent upsert / dedup key)
    text: str
    embedding: list[float]
    source_url: str
    source_type: str        # "hn" | "github" | "arxiv" | "rss" | "boilerplate"
    topic: str              # tracked classification it matched
    ingested_at: str        # ISO date (for aging/pruning)
    quality: float          # ingest-time score (see 04)
```

`Ask` answers and Research reports cite `source_url` per claim. The `id` is a hash
of normalized text so re-ingesting the same article is a no-op (dedup + idempotency
in one).

### Embeddings (local)

Embeddings come from Ollama (`nomic-embed-text` or `bge-m3`). Same model for
ingestion and query — never mix embedding models within a collection.

```python
# pa/knowledge/embeddings.py
async def embed(texts: list[str]) -> list[list[float]]:
    # POST /api/embeddings to Ollama, batched
    ...
```

### Aging & pruning

Daily ingestion accumulates noise. A scheduled `prune(older_than_days=90)` drops
stale entries; keep anything referenced by a completed build (mark `pinned=true`).
Run pruning in the same off-peak window as the digest.

---

## 2. Persistent Memory (SQLite)

SQLite is enough for a single-user local assistant (upgrade path to Postgres is a
config flip). It stores everything that must survive a restart and stay consistent
across the CLI and Slack.

### Schema (illustrative)

```sql
-- job + pipeline state (powers `pa status` / `/status`, survives restart)
CREATE TABLE jobs (
  job_id      TEXT PRIMARY KEY,
  kind        TEXT,                 -- build | research | ask
  user        TEXT,
  state       TEXT,                 -- queued|running|awaiting_approval|done|failed|cancelled
  phase       TEXT,                 -- research|architect|developer (for builds)
  idea        TEXT,
  created_at  TEXT,
  updated_at  TEXT
);

-- structured artifacts per phase (research report, blueprint, repo path)
CREATE TABLE artifacts (
  job_id   TEXT, phase TEXT, kind TEXT, content TEXT,
  PRIMARY KEY (job_id, phase, kind)
);

-- user preferences (default language, stack, workspace path, gate policy)
CREATE TABLE prefs (key TEXT PRIMARY KEY, value TEXT);

-- tracked topic classifications (mirrors config/topics.toml, editable at runtime)
CREATE TABLE topics (name TEXT PRIMARY KEY, keywords TEXT);

-- episodic memory: compact traces of past runs, for skill self-improvement
CREATE TABLE run_traces (
  job_id TEXT PRIMARY KEY, summary TEXT, outcome TEXT, lessons TEXT, created_at TEXT
);

-- rolling chat/interaction summaries (keeps the meta-agent's context small)
CREATE TABLE summaries (id INTEGER PRIMARY KEY, scope TEXT, summary TEXT, created_at TEXT);
```

### Access layer

```python
# pa/knowledge/memory.py
class Memory:
    def upsert_job(self, job: JobRow) -> None: ...
    def get_job(self, job_id: str) -> JobRow | None: ...
    def list_jobs(self, *, active_only=False) -> list[JobRow]: ...
    def save_artifact(self, job_id, phase, kind, content) -> None: ...
    def get_pref(self, key, default=None) -> str | None: ...
    def set_pref(self, key, value) -> None: ...
    def record_trace(self, trace: RunTrace) -> None: ...
```

> **Why two stores, not one:** vector DBs are bad at transactional point-reads of
> "what phase is job X in?" and SQLite is bad at semantic search. Each does the one
> thing it's good at. The engine is the only component that touches both.

---

## 3. The Knowledge↔Memory Boundary

| Question | Store |
|----------|-------|
| "Find research relevant to *web scraping rate limits*." | Knowledge Base (semantic) |
| "What phase is job `a1b2` in?" | Persistent Memory (point read) |
| "What did we learn last time we built a scraper?" | Persistent Memory `run_traces` (→ may cite KB) |
| "Has this article already been ingested?" | Knowledge Base (`id` hash) |
| "What's the user's default language preference?" | Persistent Memory `prefs` |

---

## 4. `Ask` — Agentic RAG with citations

The `Ask` command runs the retrieval pipeline above, then optionally goes
multi-hop: if the first retrieval doesn't cover the question, the agent
reformulates and retrieves again (bounded to N hops) before answering. Every
sentence in the answer carries its `source_url`. Single-hop is the default; reserve
multi-hop for genuinely compositional questions to keep local latency sane.

---

## 5. docker-compose (sketch)

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

## 6. Testing

- **Retrieval quality:** a tiny fixture corpus + a handful of (query → expected
  doc) pairs; assert the expected doc is in top-k. Guards chunking/embedding regressions.
- **Idempotency:** ingest the same article twice → one chunk set; assert no dupes.
- **Memory:** round-trip jobs/artifacts/prefs; assert `list_jobs(active_only=True)`
  reflects state transitions.

---

## Related
- [04-daily-research-agent.md](04-daily-research-agent.md) — fills the Knowledge Base
- [05-meta-agent-and-skills.md](05-meta-agent-and-skills.md) — consumes retrieval + memory
- [../personal-assistant.implementation.md](../personal-assistant.implementation.md)
