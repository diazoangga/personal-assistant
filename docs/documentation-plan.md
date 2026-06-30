# Personal Assistant Backend — Documentation Plan

> **Scope of this document:** the plan for *what we build* and *what we document* in
> `D:/personal-assistant` (the backend: cognitive engine + daemon + local web API). It is
> the source of truth for the BE architecture, the documentation set, and the build
> milestones. The companion desktop FE plan lives in
> `D:/personal-assistant-desktop/docs/documentation-plan.md` and consumes the local web
> API this backend exposes.

---

## 1. Product in one paragraph

Personal Assistant is a **continuous cognitive engine**. A 24/7 daemon senses the user's
activity (GitHub commits, browser history, Slack), an **Interest Agent** classifies that
activity into a decaying interest model, and when a topic crosses a strength threshold the
engine auto-triggers a **Research Agent** that mines a citation graph (Semantic Scholar /
arXiv / OpenAlex) and a concept knowledge graph. A **Brainstorming Agent** (LangGraph)
answers questions and ideates over that knowledge base with web search. Everything is
stored in one **Unified Knowledge Store** (SQLite in dev, PostgreSQL in prod) plus a
**Qdrant** vector index. All user actions flow through immutable **Command** objects into a
single interface-agnostic **Engine**, which streams results back as **Events**. Two
front-ends consume the same engine: a **CLI** (`pa …`) and a **local web API** (FastAPI on
`127.0.0.1:8787`) that drives the Tauri desktop app.

### Locked technical decisions
| Decision | Choice |
|---|---|
| Language / runtime | **Python ≥ 3.10**, fully async (`asyncio`) |
| LLM access | **OpenRouter** (`google/gemma-4-26b-a4b-it:free`), custom `httpx` runtime |
| LLM tool-calling | OpenRouter runtime has **no native tool-calling**; the Brainstorming Agent uses `langchain_openai.ChatOpenAI` for that path only |
| Agent framework | **LangGraph** (Brainstorming Agent only); other agents are plain async classes |
| Primary store | **Unified Knowledge Store** — one DB, `DB_TYPE`-selected: SQLite (dev) / PostgreSQL (prod) |
| Vector store | **Qdrant** (semantic search over knowledge entries) |
| Command bus | In-process **Command → Engine → EventBus** (no external broker) |
| Interfaces | **CLI** (Typer) + **local web API** (FastAPI, REST + SSE + WebSocket) |
| Research sources | Semantic Scholar (primary), arXiv (supplementary), OpenAlex (rate-limit fallback) |

---

## 2. Documentation set we will produce

This plan governs the `docs/` tree. Each file is a deliverable. Pre-rewrite material is
preserved under `docs/_archive/` until each topic below supersedes it.

```
docs/
├── documentation-plan.md              # THIS FILE — index + plan
├── architecture/
│   ├── overview.md                    # C4 context/container view: engine, agents, daemon, API, stores
│   ├── command-event-flow.md          # Command → Engine._route → EventBus → Event stream
│   ├── signal-flow.md                 # activity signal → interest model → research trigger
│   └── decisions/                     # ADRs (Context / Decision / Consequences)
│       ├── 0001-command-event-architecture.md
│       ├── 0002-unified-knowledge-store.md
│       ├── 0003-openrouter-no-native-tools.md
│       └── 0004-postgres-over-sqlite.md
├── agents/
│   ├── interest.md                    # classification + decay + research triggering
│   ├── research.md                    # 8-step citation/concept-graph pipeline
│   ├── brainstorming.md               # LangGraph 6-node interactive agent
│   └── roadmap.md                     # Meta + Opportunity agents (planned)
├── storage/
│   ├── knowledge-store.md             # the unified schema (interests, citations, concepts, sessions…)
│   ├── vector-store.md                # Qdrant collection + embedding flow
│   └── postgres.md                    # SQLite→Postgres backend, DB_TYPE selection, migration
├── connectors/
│   ├── connector-contract.md          # ActivityConnector ABC + ActivitySignal + registry
│   ├── github.md
│   ├── browser.md
│   └── slack.md
├── api/
│   ├── rest-reference.md              # every /api/* route (queries + commands)
│   └── streaming.md                   # SSE + WebSocket event envelope + EventHub buffering
├── llm/
│   └── openrouter-runtime.md          # model routing, rate limiting, retries, embeddings
├── ops/
│   ├── local-dev.md                   # poetry install, run CLI / API / daemon, tests
│   ├── configuration.md               # env vars + settings.toml reference
│   └── daemon.md                      # 24/7 service: loop, intervals, lifecycle
└── _archive/                          # pre-rewrite docs, kept for provenance
```

> **Convention:** every architecture/agent doc carries a diagram (Mermaid or ASCII) and a
> **Source of truth** footer linking the code modules it describes, so docs and code stay
> traceable. ADRs use the standard *Context / Decision / Consequences* format.

---

## 3. Backend module layout

```
personal-assistant/                    # repo root (D:/personal-assistant)
├── pyproject.toml                      # Poetry; entry point `pa`
├── docker-compose.yml                  # Qdrant (+ optional Postgres)
├── config/settings.toml                # reference defaults (config is env-driven via .env)
├── src/
│   ├── main_engine.py                  # PersonalAssistantEngine — high-level wrapper/facade
│   ├── core/
│   │   ├── engine.py                   # Engine: Command router + EventBus orchestrator
│   │   ├── commands.py                 # frozen Command dataclasses (Ask, ResearchTopic, …)
│   │   ├── events.py                   # Event types (Started, Progress, Message, Result)
│   │   ├── bus.py                      # EventBus (per-job async pub/sub)
│   │   ├── jobs.py                     # Job + JobQueue (async task tracking)
│   │   └── signals.py                  # InterestClassification + signal models
│   ├── agents/
│   │   ├── interest.py                 # InterestAgent: classify → decay → trigger
│   │   ├── research/                   # ResearchAgent: agent.py + tools/ + skills/
│   │   └── brainstorming/              # BrainstormingAgent: agent.py + graph.py + nodes/ + tools.py
│   ├── store/
│   │   ├── knowledge.py                # UnifiedKnowledgeStore (citation + concept + user graphs)
│   │   ├── vector.py                   # KnowledgeBase (Qdrant wrapper)
│   │   ├── db_connection.py            # DBConnection abstraction (? → $n rewrite for Postgres)
│   │   └── memory.py                   # legacy interest tables (being folded into knowledge.py)
│   ├── daemon/
│   │   ├── service.py                  # PersonalAssistantDaemon (24/7 loop)
│   │   ├── connector_base.py           # ActivityConnector ABC + ActivitySignal + registry
│   │   ├── manager.py                  # subprocess management (pa daemon start/stop)
│   │   └── connectors/                 # github.py, browser.py, slack.py
│   ├── llm/openrouter.py               # OpenRouterRuntime (chat, complete, embed)
│   ├── config/database.py              # DatabaseConfig.from_env() — DB_TYPE selection
│   └── adapters/
│       ├── cli/app.py                  # Typer CLI: pa ask / interests / brainstorm / daemon …
│       └── api/                        # FastAPI local web API (see §4)
│           ├── app.py                  # app factory + lifespan (engine + daemon in-process)
│           ├── queries.py              # GET /api/* dashboard reads
│           ├── commands.py             # POST /api/{ask,brainstorm,research,feedback}
│           ├── streams.py              # SSE + WS /api/events
│           ├── hub.py                  # EventHub: per-job event buffer + stream
│           ├── models.py               # pydantic request/response models
│           └── deps.py                 # DI: engine/hub/daemon/store + auth
└── tests/
```

---

## 4. Local web API surface

Loopback only (`127.0.0.1:8787`), optional `LOCAL_API_TOKEN` bearer, single user
(`LOCAL_API_USER`, default `local`). Two families: **commands** (POST → `job_id` → stream)
and **queries** (synchronous dashboard reads). Full contract in
[api/rest-reference.md](api/rest-reference.md) and [api/streaming.md](api/streaming.md).

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/ask` | Cited Q&A → job; answer streams as `message` then `result`. |
| `POST` | `/api/brainstorm` | Interactive ideation → job. |
| `POST` | `/api/research` | Manual research run (`topic`, `depth`) → job. |
| `POST` | `/api/feedback` | Record accept/reject/correct on a reference (→ `activity_log`). |
| `GET` | `/api/events/{job_id}` | SSE stream of a job's events. |
| `WS` | `/api/ws/events/{job_id}` | WebSocket stream (preferred for live). |
| `GET` | `/api/health` | Liveness + version. |
| `GET` | `/api/daemon/status` | Daemon running / pid / last ingest. |
| `GET` | `/api/stats` | Global counts (interests, concepts, citations, knowledge, questions). |
| `GET` | `/api/interests` | Interest model (filter by `min_strength`). |
| `GET` | `/api/interests/{label}/timeline` | Evidence trail for an interest. |
| `GET` | `/api/knowledge` · `/api/knowledge/search` | High-quality Q&A entries. |
| `GET` | `/api/graph/subgraph` | Concept/citation subgraph (`topic`, `depth`). |
| `GET` | `/api/citations/{id}` | Paper detail + linked concepts. |
| `GET` | `/api/research/runs` | Research run log. |
| `GET` | `/api/sessions` · `/api/sessions/{id}/turns` | Conversation history. |
| `GET` | `/api/activity` | Daemon activity log (input side of the loop). |

---

## 5. The cognitive pipeline (what the agents do)

```
                 ┌─────────── daemon (24/7) ───────────┐
   GitHub ─┐     │  fetch signals every ingest_interval │
   Browser ─┼──▶ │  → InterestAgent.process_signals()  │ ──┐
   Slack  ─┘     └──────────────────────────────────────┘   │ ResearchTopic cmds
                                                              ▼
   user ── Ask/Brainstorm/Research ──▶ Engine._route ──▶ agent ──▶ EventBus ──▶ stream
                                            │
                                            ▼
                         UnifiedKnowledgeStore  ◀── Qdrant (semantic search)
```

1. **Sense** — connectors emit `ActivitySignal`s (`connectors/*`).
2. **Classify** — Interest Agent embeds + LLM-classifies signals into topics, storing
   evidence with confidence and timestamp (`agents/interest.md`).
3. **Decay & trigger** — interest strength = `Σ confidence·exp(-age_h/720)`; crossing 0.3
   (off cooldown) emits a `ResearchTopic` command (`architecture/signal-flow.md`).
4. **Research** — 8-step pipeline builds citation + concept graphs, links them to the
   interest, and writes a `research_runs` record (`agents/research.md`).
5. **Converse** — Brainstorming Agent answers/ideates over the store + web search; high
   quality Q&A is auto-saved as `knowledge_entries` (`agents/brainstorming.md`).

---

## 6. Milestones (build + doc order)

| # | Milestone | BE deliverables | Docs |
|---|---|---|---|
| M0 ✅ | Core engine | Command/Event bus, Job queue, CLI | `architecture/{overview,command-event-flow}.md` |
| M1 ✅ | Signal flow | Interest Agent classify + decay + trigger; daemon | `architecture/signal-flow.md`, `agents/interest.md`, `ops/daemon.md` |
| M2 ✅ | Research Agent | 8-step citation/concept pipeline + connectors | `agents/research.md`, `connectors/*`, `storage/knowledge-store.md` |
| M3 ✅ | Brainstorming Agent | LangGraph 6-node agent + web search + KB | `agents/brainstorming.md`, `llm/openrouter-runtime.md` |
| M4 ✅ | Local web API | FastAPI REST + SSE/WS, in-process daemon, EventHub | `api/{rest-reference,streaming}.md` |
| M5 ✅ | Postgres | `DB_TYPE`-selected backend, `?`→`$n` rewrite, migration | `storage/postgres.md`, ADR-0004 |
| M6 ◻ | Meta + Opportunity agents | Orchestration + ranked recommendations | `agents/roadmap.md` |

---

## 7. Open questions
- **Meta/Opportunity agents** are stubs — orchestration policy and the opportunity ranking
  model are undesigned (`agents/roadmap.md`).
- **`store/memory.py` vs `store/knowledge.py`** — legacy interest tables still live in
  `memory.py`; consolidation into the unified store is incomplete.
- **Legacy `ingest/pipeline.py`** is being phased out in favour of the daemon; the CLI
  `IngestNow` path still routes through it.
- **Qdrant in prod** — collection-per-user vs shared with payload filters is not yet
  decided (`storage/vector-store.md`).
