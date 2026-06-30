---
title: Personal Assistant — Implementation Roadmap
created: 2026-06-20
updated: 2026-06-21
version: 3.0.0
status: Draft
tags:
  - implementation
  - roadmap
changelog:
  - version: 1.0.0
    date: 2026-06-20
    changes: "Initial roadmap for the SDLC project-builder paradigm"
  - version: 2.0.0
    date: 2026-06-21
    changes: >-
      Rewritten for the cognitive-engine paradigm (plans.md v3.0.0). Replaced the
      Research/Architect/Developer worker chain and `build` milestones with the
      three-loop sensing model, three cognitive agents, the Skill registry, and
      Brainstorm. Updated repo layout, core contracts, and milestones.
  - version: 3.0.0
    date: 2026-06-21
    changes: >-
      Updated for plans.md v4.0.0 (five agents). Added a Research Agent
      (triggered by Interest classification; citation + knowledge graph) and
      promoted Brainstorm from a Meta Agent mode to a full agent with web
      search. Repo layout, milestones, and config updated accordingly.
audience: Solo developer building an AI personal assistant with OpenRouter
related:
  - personal-assistant.plans.md
---

> Whenever this documentation file changes, update the `updated` field and append a new entry to `changelog` describing the revision.

# Personal Assistant — Implementation Roadmap

The consolidated build guide that ties the per-component docs together. It assumes
the foundational decisions from [personal-assistant.plans.md](personal-assistant.plans.md):
all-local Ollama (D1), symmetric CLI/Slack over a shared Core Engine (D2),
LangGraph orchestration (D3), strict Agent/Skill/Tool separation (D4), the
four-stage signal model (D5), and Meta Agent's human-reviewed self-modification
authority (D6).

Read order: this file → [impl/07-openrouter-llm-runtime.md](impl/07-openrouter-llm-runtime.md) (LLM setup)
→ [impl/01-cli-and-core-engine.md](impl/01-cli-and-core-engine.md)
→ [impl/03-vector-db-and-storage.md](impl/03-vector-db-and-storage.md)
→ [impl/04-daily-research-agent.md](impl/04-daily-research-agent.md) (activity sensing)
→ [impl/06-research-agent.md](impl/06-research-agent.md) (Research Agent)
→ [impl/02-slack-gateway.md](impl/02-slack-gateway.md)
→ [impl/05-meta-agent-and-skills.md](impl/05-meta-agent-and-skills.md) (Meta, Interest, Opportunity).

---

## 1. Guiding Principles

1. **One core, many adapters.** If a feature can't be driven from both `pa` and
   Slack with the same code path, it's in the wrong layer.
2. **Async by default.** Every user action returns a `job_id` immediately and
   streams progress (mandatory for Slack's 3s ack; pleasant on the CLI).
3. **Agent = Why, Skill = How, Tool = With What (D4).** Before adding an agent,
   check the [Skill registry](personal-assistant.plans.md#the-skill-registry-canonical--d4)
   — it's usually a skill. Memory and the vector/graph DB are tools, not agents.
4. **Context is the scarce resource.** Local models are small. Retrieval exists to
   hand each agent the *fewest* relevant tokens. Never pass raw dumps around.
5. **Continuous, not on-demand.** The engine senses and understands on a schedule;
   the Research Agent reacts to what Understanding decides matters; Insight runs on
   both a schedule and on demand (`brainstorm`/`ask`).
6. **Self-modification is always human-reviewed (D6).** The Meta Agent may propose a
   skill/prompt/tool change after a performance review; nothing applies without an
   explicit approval.
7. **Everything is inspectable.** Jobs, runs, and agent I/O are logged and
   replayable.

---

## 2. Repository Layout

A single Python package, two entrypoints (`pa` CLI and the Slack app), one engine.

```
personal-assistant/
├── pyproject.toml                # uv/pip; defines `pa` console script
├── docker-compose.yml            # Qdrant (or pgvector) + optional Postgres
├── config/
│   ├── settings.toml             # models, paths, schedule, connectors
│   └── topics.toml               # seed interest classifications (model learns more)
├── src/
│   ├── __init__.py
│   ├── core/                     # ── Core Engine (interface-agnostic) ──
│   │   ├── engine.py             # submit(command) -> job_id; event stream
│   │   ├── commands.py           # Command dataclasses (Ask, Brainstorm, ResearchTopic…)
│   │   ├── events.py             # Event types (Progress, Result, Message…)
│   │   ├── jobs.py               # async Job Queue + state machine
│   │   └── bus.py                # in-process pub/sub
│   ├── agents/                   # ── Cognitive Agents (deciders) ──
│   │   ├── meta/graph.py         # LangGraph: orchestration, classification, feedback,
│   │   │                         #   self-modification proposals (D6)
│   │   ├── meta/tools.py         # tool wrappers the graph calls
│   │   ├── interest.py           # builds/maintains the interest model; triggers Research
│   │   ├── research.py           # researches papers/GitHub/Medium/news; builds graphs
│   │   ├── opportunity.py        # generates ideas/recommendations
│   │   └── brainstorm.py         # full agent: KB + web search + Opportunity/Research handoff
│   ├── skills/                   # ── Shared Skills (transforms) ──
│   │   ├── classification.py
│   │   ├── topic_extraction.py
│   │   ├── entity_relation.py    # entity/relationship extraction
│   │   ├── graph_construction.py # citation graph + knowledge graph builders
│   │   ├── retrieval.py          # hybrid retrieval + query reformulation
│   │   ├── ranking.py            # recommendation ranking
│   │   ├── gap_analysis.py
│   │   ├── concept.py            # expansion + synthesis
│   │   ├── summarize.py          # incl. cited synthesis
│   │   ├── trend.py              # trend detection
│   │   └── loader.py             # orchestration-skill (.md) loader
│   ├── ingest/                   # ── Activity sensing pipeline (not an agent) ──
│   │   ├── connectors/           # github (activity), browser, slack, calendar
│   │   └── pipeline.py           # dedupe → score → store → emit signals
│   ├── research/                 # ── Research-source connectors (used by Research Agent) ──
│   │   └── connectors/           # arxiv, github (trending), medium, news
│   ├── store/                    # ── Storage access (Tools) ──
│   │   ├── vector.py             # Qdrant/pgvector client, hybrid search
│   │   ├── memory.py             # SQLite: profile, interest graph, opportunities, jobs
│   │   ├── graph.py              # SQLite: citation graph + knowledge graph nodes/edges
│   │   └── embeddings.py         # Ollama embeddings
│   ├── llm/
│   │   └── ollama.py             # per-role model routing + concurrency guard
│   └── adapters/                 # ── Interface Adapters (thin) ──
│       ├── cli/app.py            # Typer app -> Core Engine
│       └── slack/app.py          # Bolt app  -> Core Engine
├── skills/                       # version-controlled orchestration-skill templates
│   ├── interest-update.md
│   ├── opportunity-scan.md
│   └── research-deepen.md
└── tests/
```

> Both adapters import `pa.core`; neither imports the other. Agents import skills
> and tools; skills and tools never import agents. That dependency direction *is*
> the architecture (see [agent.architecture-guide.md](agent.architecture-guide.md)).
>
> **Note the `ingest/` vs `research/` split.** Both pull external content, but they
> are different layers: `ingest/` is a scheduled, decision-free *pipeline* feeding the
> Interest Agent with **activity** signals (D4 — not an agent). `research/` holds the
> *connectors* the **Research Agent** (a real decider) calls on demand, targeted at a
> specific topic. Same shape of code (a `Connector.fetch`), different caller and
> different trigger.

---

## 3. Core Contracts (define these first)

Lock these early; everything else is replaceable.

```python
# src/core/commands.py
@dataclass(frozen=True)
class Command:           user: str
@dataclass(frozen=True)
class Ask(Command):      query: str                       # one-shot cited Q&A
@dataclass(frozen=True)
class Brainstorm(Command): text: str; session_id: str | None = None  # interactive
@dataclass(frozen=True)
class ShowInterests(Command): view: str = "show"          # show | timeline
@dataclass(frozen=True)
class ResearchTopic(Command): topic: str; depth: str = "normal"  # manual Research Agent trigger
@dataclass(frozen=True)
class ShowGraph(Command): kind: str = "knowledge"; topic: str | None = None  # knowledge | citation
@dataclass(frozen=True)
class Opportunities(Command): action: str = "list"        # list | save | dismiss
@dataclass(frozen=True)
class ShowDigest(Command):    date: str | None = None
@dataclass(frozen=True)
class Feedback(Command):      ref: str; verdict: str       # accept | reject | correct
@dataclass(frozen=True)
class IngestNow(Command):     connector: str | None = None
@dataclass(frozen=True)
class JobStatus(Command):     job_id: str | None = None
# … Cancel, SetPref, Topics, Sources

# src/core/events.py
@dataclass(frozen=True)
class Event:             job_id: str
@dataclass(frozen=True)
class Progress(Event):   phase: str; message: str
@dataclass(frozen=True)
class Message(Event):    role: str; text: str; citations: list[str] = ()  # brainstorm turn
@dataclass(frozen=True)
class Result(Event):     ok: bool; payload: dict = field(default_factory=dict)

# src/core/engine.py
class Engine:
    async def submit(self, cmd: Command) -> str: ...        # returns job_id
    def events(self, job_id: str) -> AsyncIterator[Event]: ...
```

An adapter's whole life: build a `Command`, `await engine.submit(...)`, render
`engine.events(job_id)`. See [impl/01](impl/01-cli-and-core-engine.md) for the full
engine + CLI and [impl/02](impl/02-slack-gateway.md) for the Slack rendering.

---

## 4. Milestones (map to plan Phases 0–3)

### M0 — Spine (Week 1)
**Goal:** GitHub activity → topics → stored interest signal; `pa ask` returns a cited answer.

- [ ] `pyproject.toml`, `pa` console script, `settings.toml`
- [ ] `docker compose up` brings up Qdrant/pgvector
- [ ] **OpenRouter setup:** get API key, configure `settings.toml`; `llm/openrouter.py` routing
- [ ] **Local embeddings:** install sentence-transformers or Ollama for embeddings only
- [ ] Core contracts (`commands`, `events`, `engine`, `jobs`, `bus`)
- [ ] CLI adapter: `pa ask`, `pa status`, `pa ingest now`
- [ ] GitHub activity connector → Topic Extraction skill → signals in the store
- [ ] `store/vector.py` query returns relevant chunks; `Ask` cites sources
**Exit:** one signal source produces a stored, queryable interest signal.

### M1 — Understanding → Research bridge (Week 2)
**Goal:** an Interest classification triggers a real Research Agent run that produces a graph; Slack reaches the same engine.

- [ ] Interest Agent: build/maintain the interest model (Topic Extraction + Clustering + Trend Detection)
- [ ] **Research Agent**, papers-first: triggered by a new/strengthened classification →
  arXiv connector → Entity/Relationship Extraction → Citation Graph Construction
- [ ] `store/graph.py` (citation graph + knowledge graph node/edge tables)
- [ ] `pa research <topic>` manual trigger; `pa graph show` (citation|knowledge)
- [ ] Slack adapter (Socket Mode): `/ask`, `/interests`, `/research` → same engine
- [ ] `interests`, `topics`, `sources` commands (CLI + Slack)
**Exit:** a real interest triggers real research; the resulting citation graph is queryable.

### M2 — Opportunity + Brainstorm (Weeks 3–4)
**Goal:** ask the KB or the web anything; get traceable proposals; brainstorm can trigger fresh research.

- [ ] Research Agent: add GitHub (trending/relevant), Medium, news connectors;
  Knowledge Graph Construction
- [ ] Opportunity Agent: Concept Synthesis + Gap Analysis + Recommendation Ranking,
  reading the Research Agent's graphs
- [ ] **Brainstorming Agent** (full agent, own LangGraph subgraph): KB retrieval +
  **web search** tool + routing to ideation (Opportunity Agent) or a deep-dive
  (Research Agent, on demand)
- [ ] `save idea` → opportunities store; `feedback` capture
- [ ] `pa brainstorm` REPL (CLI) + Slack thread session
**Exit:** the flagship loop works end-to-end (see [brainstorm feature](personal-assistant.brainstorm-feature.md)).

### M3 — Continuous & self-improving (Ongoing)
- [ ] Browser / Slack / calendar activity connectors (privacy-reviewed; consent + retention policy)
- [ ] Activity classification (Meta Agent + Classification skill)
- [ ] Proactive insight digest + alerts on high-signal hits; data aging/pruning
- [ ] Agent performance tracking
- [ ] **Meta self-modification proposals (D6)**: skill edits, prompt edits, tool
  wiring — always landed as a reviewable diff, never auto-applied

---

## 5. Configuration

`config/settings.toml` (illustrative):
```toml
[models]
meta      = "google/gemma-3b-european-union:free"  # routing, classification, synthesis orchestration (free tier)
reasoning = "google/gemma-3b-european-union:free"  # heavier synthesis (opportunity/brainstorm), on demand
embedding = "nomic-embed-text"                      # local embedding (still needed for KB)

[runtime]
openrouter_api_key = "${OPENROUTER_API_KEY}"        # required: your OpenRouter API key
openrouter_base_url = "https://openrouter.ai/api/v1"
max_concurrent_requests = 3                         # rate limit guard for free tier
data_dir          = "~/.assistant"

[schedule]
sensing_cron    = "0 * * * *"    # activity sensing: hourly
understand_cron = "0 7 * * *"    # interest-model rollup
digest_cron     = "30 7 * * *"   # insight digest delivery

[connectors.activity]
enabled = ["github"]             # browser/slack/calendar added in M3

[connectors.research]
enabled = ["arxiv"]              # github_trending/medium/news added in M2

[storage]
vector_backend = "qdrant"       # or "pgvector"
memory_db      = "~/.assistant/memory.sqlite"
graph_db       = "~/.assistant/graph.sqlite"

[research]
max_depth      = 2               # citation-chase hops per triggered run
novelty_threshold = 0.75         # below this similarity to existing graph, treat as new node

[slack]
mode = "socket"
digest_channel = "#assistant"

[self_improvement]
mode = "human_reviewed"          # D6 — the only supported value; documented for clarity, not a toggle to "auto"
```

`config/topics.toml` (seed classifications; the Interest Agent learns more):
```toml
[[topic]]
name = "LLM agents & orchestration"
keywords = ["agent", "langgraph", "tool calling", "rag"]
[[topic]]
name = "Local inference"
keywords = ["ollama", "quantization", "vllm", "gguf"]
```

---

## 6. Cross-Cutting Concerns

| Concern | Approach |
|---------|----------|
| **Privacy (D1)** | Signals are personal. Filter sensitive data before OpenRouter API calls; connectors are opt-in; define a retention/aging policy before enabling browser/Slack/calendar. |
| **Secrets** | `.env` (Slack tokens, GitHub PAT, web search API key, **OpenRouter API key**). Never commit. |
| **Concurrency / Rate Limits** | `llm/openrouter.py` enforces free tier rate limits; loops scheduled to avoid burst requests. |
| **Observability** | Structured job logs + LangGraph checkpointer for run replay; `pa status`. |
| **Idempotency** | Ingest/research keys on a content hash so re-runs don't duplicate KB or graph entries. |
| **Provenance** | Every recommendation/answer traces to signal/source/graph-node IDs ("why this"). |
| **Self-modification gate (D6)** | Meta Agent proposals land as a diff under review; CI/tooling should make "unreviewed diff applied" structurally impossible, not just discouraged. |
| **Testing** | Unit-test contracts, skills (pure transforms — easy), and retrieval; stub model for agent-graph tests. |

---

## 7. Definition of Done (per feature)

1. Driven by a Core Engine `Command` (not adapter logic).
2. Reachable from **both** CLI and Slack (if user-facing).
3. Emits progress + a final `Result` (or `Message` turns for brainstorm).
4. Recommendations/answers carry citations/provenance.
5. Has a log trail via `pa status <job>` and at least a stub-model smoke test.

---

## Related Documents
- [personal-assistant.plans.md](personal-assistant.plans.md) — architecture & features
- [personal-assistant.brainstorm-feature.md](personal-assistant.brainstorm-feature.md) — flagship feature
- [agent.architecture-guide.md](agent.architecture-guide.md) — how to extend
- [impl/01-cli-and-core-engine.md](impl/01-cli-and-core-engine.md)
- [impl/02-slack-gateway.md](impl/02-slack-gateway.md)
- [impl/03-vector-db-and-storage.md](impl/03-vector-db-and-storage.md)
- [impl/04-daily-research-agent.md](impl/04-daily-research-agent.md) — activity sensing pipeline
- [impl/05-meta-agent-and-skills.md](impl/05-meta-agent-and-skills.md) — Meta, Interest, Opportunity
- [impl/06-research-agent.md](impl/06-research-agent.md) — Research Agent
