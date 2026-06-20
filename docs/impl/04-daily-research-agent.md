---
title: "Implementation: Daily Research Agent"
created: 2026-06-20
updated: 2026-06-20
version: 1.0.0
status: Draft
tags: [implementation, research, ingestion, digest]
related:
  - ../personal-assistant.plans.md
  - 03-vector-db-and-storage.md
---

> Whenever this documentation file changes, update the `updated` field and append a new entry to `changelog` describing the revision.

# Implementation: Daily Research Agent (Loop 1)

The Daily Research Agent runs on a schedule, independent of any user command. It
fills the Knowledge Base so that when a `build` runs later, the Meta-Agent already
has relevant research on hand. Its visible output is a categorized digest in
`#daily-intelligence` (and `pa digest`).

```
scheduler @ 07:00
      │
      ▼
  pull sources ─► dedupe ─► quality score ─► semantic chunk ─► embed ─► store (KB)
      │                                                                     │
      └──────────────────────────► rank per topic ──► build digest ◄────────┘
                                                          │
                                          deliver: Slack #daily-intelligence + CLI
```

---

## 1. Sources (pluggable adapters)

Each source is a small adapter returning normalized `RawItem`s. Adding a source is
adding one file — no pipeline changes.

```python
# pa/research/sources/base.py
@dataclass
class RawItem:
    title: str
    url: str
    body: str            # fetched/summarized text
    source_type: str     # "hn" | "github" | "arxiv" | "rss"
    published_at: str

class Source(Protocol):
    async def fetch(self, topics: list[Topic]) -> list[RawItem]: ...
```

| Source | Adapter | Notes |
|--------|---------|-------|
| Hacker News | `sources/hn.py` | Algolia API; filter by topic keywords + min points |
| GitHub Trending | `sources/github.py` | Trending repos by language/topic |
| arXiv | `sources/arxiv.py` | Query API per topic; abstracts |
| RSS / blogs | `sources/rss.py` | User-listed feeds in `config` |

Sources read the tracked **topics** (from `config/topics.toml` / the `topics`
table) so ingestion stays focused on what the user actually cares about.

---

## 2. Ingestion Pipeline

```python
# pa/research/ingest.py
async def ingest(items: list[RawItem]) -> IngestReport:
    items = dedupe(items)                 # content-hash; drop already-known
    items = [i for i in items if quality(i) >= THRESHOLD]
    chunks = []
    for item in items:
        for text in semantic_chunks(item.body):
            chunks.append(make_chunk(item, text))   # carries provenance + quality
    await knowledge.upsert(chunks)        # idempotent on chunk.id
    return IngestReport(new=len(chunks), kept_items=len(items))
```

### Deduplication
Two layers: (1) **exact** — `chunk.id` is a hash of normalized text, so re-ingesting
the same article is a no-op; (2) **near-duplicate** — before upsert, check cosine
similarity against the KB; if a near-identical chunk exists, keep the
higher-quality source and skip the rest. This is what keeps the KB from rotting
into noise over weeks of daily runs.

### Quality scoring
A cheap score gates what enters the KB. Combine signals available at ingest:
source authority (e.g. HN points, GitHub stars), recency, topic-match strength
(retrieval similarity to the topic's keywords), and body length/substance. Items
below threshold are dropped, not stored. Store the score on the chunk so retrieval
can prefer higher-quality material on ties.

### Chunking & embedding
Semantic chunking + local embeddings — see
[03-vector-db-and-storage.md](03-vector-db-and-storage.md) §1. Reuse that code; the
research loop is a *producer* for the same store the SDLC pipeline *consumes*.

---

## 3. The Digest

After ingest, rank the day's new items **per topic** and render a digest. Keep it
skimmable: 3–5 items per topic, each with a one-line "why it matters."

```python
# pa/research/digest.py
async def build_digest(report: IngestReport, topics: list[Topic]) -> Digest:
    sections = []
    for topic in topics:
        top = rank(report.items_for(topic), k=5)     # quality + recency + match
        sections.append(DigestSection(topic.name, [summarize_one_line(i) for i in top]))
    return Digest(date=today(), sections=sections)
```

Delivery is interface-symmetric:
- **Slack:** Block Kit — header + one section per topic + `/ask` footer hint. Posted
  via the Slack adapter's `post_digest()` sink (see
  [02-slack-gateway.md](02-slack-gateway.md) §5).
- **CLI:** `pa digest [date]` renders the same `Digest` object with Rich.

The digest is produced once by the Core Engine and rendered by whichever interface
asks for it — never computed twice.

---

## 4. Scheduling & Compute Safety

```toml
[schedule]
daily_research_cron = "0 7 * * *"
build_quiet_hours   = ["07:00", "08:00"]
```

- **Scheduler:** cron calling `pa research now`, or APScheduler inside a long-running
  engine process. Either submits a `ResearchNow` command — the same path the user's
  manual `/research` uses (parity again).
- **Concurrency guard (critical on local hardware):** the digest job loads the
  embedding model; a `build` loads the big worker model. The guard in
  `llm/ollama.py` ensures these don't co-load and thrash VRAM. If a build is
  queued during quiet hours, the digest waits.

---

## 5. Proactive Alerts (Phase 3)

Beyond the scheduled digest, the agent can **initiate contact** when a tracked
topic gets a high-signal hit (e.g. a release or paper far above the quality
threshold). This is the 2026 "assistant reaches out when something needs your
attention" pattern. Implement as a post-ingest check that, on a strong hit, submits
a lightweight notify command → a single Slack message, rate-limited so it never
becomes noise.

---

## 6. The Loop 1 → Loop 2 Bridge

This is the payoff. When `build` runs, the Research Worker's *first* move is a
Knowledge Base query (see [05-meta-agent-and-skills.md](05-meta-agent-and-skills.md)) —
hitting research this agent already ingested. Most of the time the worker answers
feasibility from local knowledge and never touches the live web. Yesterday's
reading becomes today's feasibility report; that's the whole reason Loop 1 exists.

---

## 7. Testing

- **Source adapters:** record/replay fixtures (VCR-style); assert normalization to `RawItem`.
- **Dedup:** feed overlapping batches; assert no duplicate chunks and that the
  higher-quality source wins near-dup conflicts.
- **Digest:** given a fixed `IngestReport`, snapshot the rendered Block Kit + CLI output.
- **Bridge test:** ingest a fixture, then run a Research Worker query and assert it
  retrieves the ingested chunk without a network call.

---

## Related
- [03-vector-db-and-storage.md](03-vector-db-and-storage.md) — the store this fills
- [02-slack-gateway.md](02-slack-gateway.md) — digest delivery sink
- [05-meta-agent-and-skills.md](05-meta-agent-and-skills.md) — the consumer
- [../personal-assistant.implementation.md](../personal-assistant.implementation.md)
