---
title: Personal Assistant — Implementation Roadmap
created: 2026-06-20
updated: 2026-06-20
version: 1.0.0
status: Draft
tags:
  - implementation
  - roadmap
audience: Solo developer building a local Linux-based AI personal assistant
related:
  - personal-assistant.plans.md
---

> Whenever this documentation file changes, update the `updated` field and append a new entry to `changelog` describing the revision.

# Personal Assistant — Implementation Roadmap

This is the consolidated build guide that ties the per-component docs together. It
assumes the three foundational decisions from
[personal-assistant.plans.md](personal-assistant.plans.md): all-local Ollama,
symmetric CLI/Slack over a shared Core Engine, and LangGraph orchestration.

Read order: this file → [impl/01-cli-and-core-engine.md](impl/01-cli-and-core-engine.md)
→ [impl/03-vector-db-and-storage.md](impl/03-vector-db-and-storage.md)
→ [impl/04-daily-research-agent.md](impl/04-daily-research-agent.md)
→ [impl/02-slack-gateway.md](impl/02-slack-gateway.md)
→ [impl/05-meta-agent-and-skills.md](impl/05-meta-agent-and-skills.md).

---

## 1. Guiding Principles

1. **One core, many adapters.** Business logic never lives in an interface. If a
   feature can't be driven from both `pa` and Slack with the same code path, it's
   in the wrong layer.
2. **Async by default.** Every user action returns a `job_id` immediately and
   streams progress. This is mandatory for Slack (3-second ack rule) and pleasant
   for the CLI.
3. **Context is the scarce resource.** Local models are small. The Vector DB
   exists to hand each agent the *fewest* relevant tokens. Never pass raw dumps
   between phases.
4. **Deterministic orchestration, flexible execution.** Skills fix the routing;
   tools do the work. (See [impl/05-meta-agent-and-skills.md](impl/05-meta-agent-and-skills.md).)
5. **Everything is inspectable.** Jobs, runs, and agent I/O are logged and
   replayable. A solo dev must be able to debug a bad run without re-running it.

---

## 2. Repository Layout

A single Python package, two entrypoints (`pa` CLI and the Slack app), one engine.

```
personal-assistant/
├── pyproject.toml                # uv/pip; defines `pa` console script
├── docker-compose.yml            # Qdrant (or pgvector) + optional Postgres
├── config/
│   ├── settings.toml             # models, paths, schedule, source list
│   └── topics.toml               # tracked interest classifications
├── pa/
│   ├── __init__.py
│   ├── core/                     # ── Core Engine (interface-agnostic) ──
│   │   ├── engine.py             # submit(command) -> job_id; event stream
│   │   ├── commands.py           # Command dataclasses (Build, Research, Ask…)
│   │   ├── events.py             # Event types (Progress, Result, ApprovalNeeded)
│   │   ├── jobs.py               # async Job Queue + state machine
│   │   └── bus.py                # in-process pub/sub
│   ├── agents/                   # ── Meta-Agent + Workers ──
│   │   ├── meta/graph.py         # LangGraph state machine
│   │   ├── meta/tools.py         # dispatch_* + query_knowledge_base tools
│   │   ├── workers/research.py
│   │   ├── workers/architect.py
│   │   └── workers/developer.py
│   ├── research/                 # ── Daily Research Loop ──
│   │   ├── sources/              # source adapters (hn, github, arxiv, rss)
│   │   ├── ingest.py             # dedupe → chunk → embed → store
│   │   └── digest.py             # build + deliver digest
│   ├── knowledge/                # ── Storage access ──
│   │   ├── vector.py             # Qdrant/pgvector client, hybrid search
│   │   ├── memory.py             # SQLite persistent memory (state/prefs)
│   │   └── embeddings.py         # Ollama embeddings
│   ├── llm/
│   │   └── ollama.py             # per-role model routing + concurrency guard
│   ├── skills/                   # loader; skill .md files live in ~/assistant/skills
│   └── adapters/                 # ── Interface Adapters (thin) ──
│       ├── cli/app.py            # Typer app -> Core Engine
│       └── slack/app.py          # Bolt app  -> Core Engine
├── skills/                       # version-controlled skill templates (seed copies)
│   └── sdlc-orchestration.md
└── tests/
```

> Both `adapters/cli/app.py` and `adapters/slack/app.py` import `pa.core` and
> `pa.core.commands`. Neither imports the other. That import boundary *is* the
> architecture.

---

## 3. Core Contracts (define these first)

These types are the contract every layer depends on. Lock them early; everything
else is replaceable.

```python
# pa/core/commands.py
@dataclass(frozen=True)
class Command: ...
@dataclass(frozen=True)
class Build(Command):    idea: str; user: str; auto_approve: bool = False
@dataclass(frozen=True)
class ResearchNow(Command): user: str
@dataclass(frozen=True)
class Ask(Command):      query: str; user: str
@dataclass(frozen=True)
class Approve(Command):  job_id: str; user: str
# … Cancel, SetPref, Topics, Skills

# pa/core/events.py
@dataclass(frozen=True)
class Event: job_id: str
@dataclass(frozen=True)
class Progress(Event):       phase: str; message: str
@dataclass(frozen=True)
class ApprovalNeeded(Event): phase: str; preview: str
@dataclass(frozen=True)
class Result(Event):         payload: dict; ok: bool

# pa/core/engine.py
class Engine:
    async def submit(self, cmd: Command) -> str: ...       # returns job_id
    def events(self, job_id: str) -> AsyncIterator[Event]: ...
```

An adapter's whole life: build a `Command`, `await engine.submit(...)`, then render
`engine.events(job_id)`. See [impl/01-cli-and-core-engine.md](impl/01-cli-and-core-engine.md)
for the full engine and CLI; [impl/02-slack-gateway.md](impl/02-slack-gateway.md)
for the Slack rendering of the same stream.

---

## 4. Milestones (maps to plan Phases 0–3)

### M0 — Tracer Bullet (Week 1)
**Goal:** `pa build "..."` runs a single Research Worker locally and prints a report.

- [ ] `pyproject.toml`, `pa` console script, `settings.toml`
- [ ] `docker compose up` brings up Qdrant/pgvector
- [ ] Ollama installed; pull meta + worker + embedding models; `llm/ollama.py` routing
- [ ] Core contracts (`commands`, `events`, `engine`, `jobs`, `bus`)
- [ ] CLI adapter: `pa build`, `pa status`
- [ ] Research Worker (single agent) returns a Markdown report
- [ ] `knowledge/vector.py` query returns relevant chunks
**Exit:** end-to-end skeleton proves the concept on local hardware.

### M1 — Daily Research + Slack parity (Week 2)
**Goal:** the digest fills the KB; Slack drives the same engine as the CLI.

- [ ] Source adapters: Hacker News, GitHub Trending, arXiv, RSS
- [ ] `ingest.py`: dedupe → semantic chunk → embed → store with provenance
- [ ] `digest.py`: categorized digest → `#daily-intelligence` + `pa digest`
- [ ] Scheduler (cron/APScheduler) at 07:00, off-peak from build hours
- [ ] Slack adapter (Socket Mode): `/build`, `/status`, `/digest` → same engine
- [ ] `topics` command (CLI + Slack) editing `config/topics.toml`
**Exit:** KB grows daily with deduped entries; both interfaces reach parity on shared commands.

### M2 — Full SDLC pipeline (Weeks 3–4)
**Goal:** the Meta-Agent orchestrates all three workers with gates and recovery.

- [ ] LangGraph Meta-Agent: nodes for research/architect/developer + conditional edges
- [ ] Skill loader + `sdlc-orchestration.md`
- [ ] Architect Worker (structure + schema + API contracts)
- [ ] Developer Worker (code + tests → `~/projects/<name>/`, optional GitHub push)
- [ ] Re-route on lint/test failure (developer loop-back edge)
- [ ] HITL gate: `ApprovalNeeded` event → Slack button / `pa approve`
- [ ] Hybrid retrieval + rerank in `knowledge/vector.py`
**Exit:** `build` produces a scaffolded, lint-passing repo with a human gate between phases.

### M3 — Polish & Hardening (Ongoing)
- [ ] Vector DB aging/pruning job
- [ ] Quality scoring on ingest
- [ ] Proactive alerts on major topic hits
- [ ] Episodic memory + human-reviewed skill self-improvement
- [ ] Compute metering dashboard (`pa status --compute`)

---

## 5. Configuration

`config/settings.toml` (illustrative):
```toml
[models]
meta      = "qwen3:8b"          # fast routing
worker    = "qwen3-coder:30b"   # loaded on demand
embedding = "nomic-embed-text"

[runtime]
ollama_host       = "http://localhost:11434"
max_loaded_models = 1           # concurrency guard: don't co-load worker + digest
workspace         = "~/projects"

[schedule]
daily_research_cron = "0 7 * * *"
build_quiet_hours   = ["07:00", "08:00"]   # digest won't run if a build is queued

[storage]
vector_backend = "qdrant"       # or "pgvector"
memory_db      = "~/.assistant/memory.sqlite"

[slack]
mode = "socket"                 # no public endpoint needed
digest_channel = "#daily-intelligence"
```

`config/topics.toml`:
```toml
[[topic]]
name = "LLM reasoning & optimization"
keywords = ["reasoning", "inference", "quantization", "agent"]
[[topic]]
name = "Web3 security"
keywords = ["smart contract", "audit", "reentrancy"]
```

---

## 6. Cross-Cutting Concerns

| Concern | Approach |
|---------|----------|
| **Secrets** | `.env` (Slack tokens). Never commit. Local-only models need no API keys. |
| **Concurrency / VRAM** | `llm/ollama.py` serializes heavy model loads; scheduler respects `build_quiet_hours`. |
| **Observability** | Structured job logs + LangGraph checkpointer for run replay; `pa status` surfaces it. |
| **Idempotency** | Ingest keys on a content hash so re-runs don't duplicate KB entries. |
| **Failure handling** | Worker failures re-route inside the graph; only unrecovered failures emit a failed `Result`. |
| **Testing** | Unit-test core contracts + retrieval; use a tiny stub model for agent-graph tests. |

---

## 7. Definition of Done (per feature)

A feature is done when:
1. It is driven by a Core Engine `Command` (not adapter logic).
2. It is reachable from **both** CLI and Slack (if user-facing).
3. It emits progress + a final `Result` event.
4. It has a log trail inspectable via `pa status <job>`.
5. It has at least a smoke test against a stub model.

---

## Related Documents
- [personal-assistant.plans.md](personal-assistant.plans.md) — architecture & feature plan
- [impl/01-cli-and-core-engine.md](impl/01-cli-and-core-engine.md)
- [impl/02-slack-gateway.md](impl/02-slack-gateway.md)
- [impl/03-vector-db-and-storage.md](impl/03-vector-db-and-storage.md)
- [impl/04-daily-research-agent.md](impl/04-daily-research-agent.md)
- [impl/05-meta-agent-and-skills.md](impl/05-meta-agent-and-skills.md)
- [agent.architecture-guide.md](agent.architecture-guide.md)
