# Architecture Overview

How the backend is put together: one interface-agnostic engine, five cognitive agents
(three implemented), one unified store, and two front-ends (CLI + local web API) that
drive the same engine.

## Container view

```
┌──────────────┐        ┌───────────────────────────────────────────────┐
│ CLI (Typer)  │        │ Local Web API (FastAPI, 127.0.0.1:8787)        │
│ pa ask/...   │        │ queries.py · commands.py · streams.py · hub.py │
└──────┬───────┘        └───────────────────────┬───────────────────────┘
       │  Command                                │  Command + EventHub
       └──────────────────┬─────────────────────┘
                          ▼
            ┌───────────────────────────────┐
            │ PersonalAssistantEngine        │  (main_engine.py — facade)
            │  ├─ core.Engine (router + bus) │
            │  ├─ OpenRouterRuntime (llm)    │
            │  ├─ UnifiedKnowledgeStore      │
            │  ├─ KnowledgeBase (Qdrant)     │
            │  └─ agents: interest/research/ │
            │            brainstorm          │
            └───────────────┬───────────────┘
                            │
        ┌───────────────────┼─────────────────────┐
        ▼                   ▼                     ▼
  Interest Agent      Research Agent       Brainstorming Agent
  classify+decay      8-step pipeline      LangGraph (6 nodes)
        │                   │                     │
        └─────────► UnifiedKnowledgeStore ◄───────┘   + Qdrant vector index
                            ▲
                 ┌──────────┴───────────┐
                 │ Daemon (24/7 loop)   │  fetches ActivitySignals
                 │ github/browser/slack │  → engine.process_activity_signals()
                 └──────────────────────┘
```

## The pieces

| Component | Module | Responsibility |
|---|---|---|
| **Engine** | `core/engine.py` | Routes each `Command` type to a handler coroutine; handlers publish `Event`s to the `EventBus`. Interface-agnostic — knows nothing about CLI vs HTTP. |
| **Facade** | `main_engine.py` | `PersonalAssistantEngine` wires the LLM, stores, and agents together, exposes high-level coroutines (`ask`, `research`, `brainstorm`) that carry conversation/knowledge side effects. |
| **Agents** | `agents/*` | The cognitive work. Interest + Research are plain async classes; Brainstorming is a LangGraph `StateGraph`. |
| **Stores** | `store/*` | `UnifiedKnowledgeStore` (one relational DB for everything) + `KnowledgeBase` (Qdrant vectors). |
| **Daemon** | `daemon/service.py` | Background loop: poll connectors → classify via Interest Agent → submit `ResearchTopic` commands. |
| **LLM** | `llm/openrouter.py` | `OpenRouterRuntime` — chat/complete/embed with rate limiting and retries. |
| **Adapters** | `adapters/{cli,api}` | Two thin transports over the same engine. |

## Two front-ends, one engine

Both transports build a `Command`, hand it to the engine, and render the resulting
`Event` stream. The CLI does this in-process and prints; the web API registers a job in an
`EventHub`, returns a `job_id`, and lets the desktop client stream events over SSE/WS. See
[command-event-flow.md](command-event-flow.md).

The web API runs the **engine and the daemon in the same process** (`adapters/api/app.py`
lifespan), sharing one knowledge store on disk — so a daemon-triggered research run and a
user-triggered one land in the same place and stream through the same hub.

## Data stores at a glance

- **UnifiedKnowledgeStore** (`store/knowledge.py`) — a single relational DB (SQLite in dev,
  PostgreSQL in prod, selected by `DB_TYPE`) holding the interest model, citation graph,
  concept graph, cross-reference links, research runs, conversations, and knowledge
  entries. See [storage/knowledge-store.md](../storage/knowledge-store.md).
- **KnowledgeBase** (`store/vector.py`) — Qdrant collection for semantic search over
  knowledge entries. See [storage/vector-store.md](../storage/vector-store.md).

## What is *not* built yet

The **Meta Agent** (orchestration / performance review) and **Opportunity Agent**
(ranked recommendations) are stubs. The `core/engine.py` router already reserves routes
(`Opportunities`, `ShowDigest`) that raise until those agents are registered. See
[agents/roadmap.md](../agents/roadmap.md).

---

> **Source of truth:** `src/main_engine.py`, `src/core/engine.py`,
> `src/adapters/api/app.py`, `src/daemon/service.py`.
