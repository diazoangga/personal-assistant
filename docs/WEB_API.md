# Local Web API — `src/adapters/api`

> The HTTP surface the **Personal Assistant Desktop** app (Tauri) talks to.
> Replaces the deleted Telegram Mini App gateway (`src/adapters/telegram/`).
>
> **Status:** design / contract. This document is the source of truth for the
> `src/adapters/api` package that supersedes the Telegram adapter.
> **Last updated:** 2026-06-24

---

## 1. Why this exists

The old `src/adapters/telegram/` package bundled three concerns into one process:
a FastAPI server, a daemon, and a Telegram long-polling bot — and gated every request
behind Telegram `initData` HMAC validation.

The desktop app needs none of the Telegram parts. It needs a **plain localhost HTTP
API** with:

- command submission (`ask`, `brainstorm`, `research`, …) returning a `job_id`,
- live event streaming per job (SSE + WebSocket),
- **synchronous read endpoints** for the dashboards (interests, knowledge, graph,
  stats, activity, daemon status) — these did **not** exist in the Telegram adapter
  and are new here.

The engine (`PersonalAssistantEngine`), command/event model, and `UnifiedKnowledgeStore`
are unchanged and fully reused.

---

## 2. Process model

`python -m src.adapters.api` (or a new `pa serve` CLI command) runs **two** concurrent
async tasks in one process, sharing a single `PersonalAssistantEngine` and `knowledge.db`:

```
┌─ src/adapters/api/app.py ───────────────────────────────────────────┐
│  lifespan():                                                         │
│    engine = PersonalAssistantEngine(config); await engine.initialize │
│    daemon = PersonalAssistantDaemon(config); task = daemon.run()     │
│    set_dependencies(engine)                                          │
│  uvicorn.Server(app).serve()   # REST + SSE + WS on 127.0.0.1:8787   │
└──────────────────────────────────────────────────────────────────────┘
```

Two ways work gets done (unchanged from the engine's design):

- **Command path (async, streamed):** `POST /api/{cmd}` → `engine.submit(cmd)` → `job_id`.
  The client then subscribes to `GET /api/events/{job_id}` (SSE) or
  `WS /api/ws/events/{job_id}` and renders `Started → Progress → Message → Result`.
  Used for `research`, `brainstorm`, `ask` (anything long-running).
- **Query path (sync, one-shot):** `GET /api/...` reads straight from the store and
  returns JSON. Used for every dashboard panel.

> **Note on `ask`/`brainstorm`:** the CLI calls `engine.ask()` / `engine.brainstorm()`
> directly (Path A) because the `Ask`/`Brainstorm` command handlers reference agents
> that aren't registered (see `SYSTEM_DOCUMENTATION.md` §3.2). The web API mirrors the
> **CLI's** approach: `POST /api/ask` and `POST /api/brainstorm` call the engine methods
> directly and return the answer in the `Result`, rather than routing through
> `submit()`. `POST /api/research` uses the real command path (it has a registered agent).

---

## 3. Configuration

| Variable | Default | Meaning |
|---|---|---|
| `LOCAL_API_HOST` | `127.0.0.1` | Bind address. Keep loopback — this is a local app. |
| `LOCAL_API_PORT` | `8787` | Port the Tauri app connects to. |
| `LOCAL_API_TOKEN` | _(unset)_ | If set, every request must send `Authorization: Bearer <token>`. Optional; loopback binding is the primary guard. |
| `LOCAL_API_USER` | `local` | The `user` field stamped onto every `Command`. Single-user app. |

CORS: allow the Tauri dev origin (`http://localhost:1420` — Vite's Tauri default) and
the `tauri://localhost` / `https://tauri.localhost` production origins. No `initData`,
no Telegram middleware.

---

## 4. Endpoints

Base path: `/api`. All responses are JSON unless noted.

### 4.1 Meta

| Method | Path | Returns |
|---|---|---|
| `GET` | `/api/health` | `{ "status": "ok", "version": "0.1.0" }` |
| `GET` | `/api/daemon/status` | `{ "running": bool, "pid": int \| null, "last_ingest": iso8601 \| null }` |

### 4.2 Command path (returns a job)

Each returns `{ "job_id": "<uuid>", "kind": "<cmd>" }` immediately; stream the job for output.

| Method | Path | Body | Maps to |
|---|---|---|---|
| `POST` | `/api/ask` | `{ "query": str, "session_id"?: str }` | `engine.ask()` |
| `POST` | `/api/brainstorm` | `{ "text": str, "session_id"?: str }` | `engine.brainstorm()` |
| `POST` | `/api/research` | `{ "topic": str, "depth"?: "shallow"\|"normal"\|"deep" }` | `ResearchTopic` → `engine.submit()` |
| `POST` | `/api/feedback` | `{ "ref": str, "verdict": "accept"\|"reject"\|"correct", "note"?: str }` | `Feedback` |

> `depth` accepts the string enum **or** an int 1–5 from the UI slider; the server maps
> `1–2 → shallow`, `3 → normal`, `4–5 → deep`.

### 4.3 Event streaming (per job)

| Method | Path | Protocol |
|---|---|---|
| `GET` | `/api/events/{job_id}` | Server-Sent Events; each `data:` line is an `EventUpdate`; closes after `result`. |
| `WS` | `/api/ws/events/{job_id}` | WebSocket; one JSON `EventUpdate` per message; closes after `result`. |

`EventUpdate` envelope (identical to the old adapter, so the client mapping is reusable):

```jsonc
{ "event_type": "started",  "job_id": "…", "payload": { "kind": "research" } }
{ "event_type": "progress", "job_id": "…", "payload": { "phase": "fetch", "message": "Fetching arXiv papers…", "pct": 0.4 } }
{ "event_type": "message",  "job_id": "…", "payload": { "role": "assistant", "text": "…", "citations": ["…"] } }
{ "event_type": "result",   "job_id": "…", "payload": { "ok": true, "data": { … } } }
```

`research` result `data`: `{ topic, papers_found, concepts_extracted, relationships_found, summary, elapsed_seconds }`.

### 4.4 Query path (dashboards — synchronous reads)

These are **new**. They read the store directly via `UnifiedKnowledgeStore` (and
`DaemonManager`) and return data immediately. Backing method shown for implementers.

| Method | Path | Query params | Backing call | Feeds UI |
|---|---|---|---|---|
| `GET` | `/api/stats` | — | `store.get_stats()` | Global Cognitive Stats panel |
| `GET` | `/api/interests` | `min_strength=0.0` | `store.get_interests(min_strength)` | Interest Decay Matrix |
| `GET` | `/api/interests/{label}/timeline` | `limit=50` | query `interest_signal_evidence` | Interest drill-down / evidence trail |
| `GET` | `/api/knowledge` | `min_quality=0.65`, `limit=50` | `store.get_knowledge_entries()` | High-Quality Digests notebook |
| `GET` | `/api/knowledge/search` | `q=`, `limit=20` | `store.search_knowledge_entries()` | Notebook search |
| `GET` | `/api/graph/subgraph` | `topic=`, `depth=2` | `store.relevant_subgraphs(interests=[topic], max_depth=depth)` | Knowledge Graph Explorer |
| `GET` | `/api/citations/{id}` | — | `store.get_citation()` + `store.get_linked_concepts_for_citation()` | Citation Viewer |
| `GET` | `/api/research/runs` | `topic?=`, `limit=20` | `store.get_research_runs()` | Research Logs |
| `GET` | `/api/sessions` | `limit=50` | query `conversation_sessions` | Session list (sidebar) |
| `GET` | `/api/sessions/{id}/turns` | — | `store.get_conversation_history()` | Chat history replay |
| `GET` | `/api/activity` | `limit=50` | query `activity_log` | Daemon activity stream |

#### Representative response shapes

`GET /api/stats`
```json
{ "interests": 12, "concepts": 412, "citations": 89,
  "research_runs": 7, "knowledge_entries": 142 }
```
> The mockup's "Total Questions / Knowledge Seeds / Concepts Mapped" map to
> `user_stats.total_questions`, `knowledge_entries`, and `concepts` respectively.
> `get_stats()` covers counts; `total_questions` comes from `store.get_user_stats(user)`.

`GET /api/interests`
```json
[ { "id": "…", "label": "GraphRAG", "strength": 0.85, "last_active": "2026-06-24T…" },
  { "id": "…", "label": "Causal Inference", "strength": 0.55, "last_active": "…" } ]
```

`GET /api/graph/subgraph?topic=GraphRAG`
```json
{ "nodes": [ { "id": "…", "label": "PageRank", "category": "method" } ],
  "edges": [ { "source": "…", "target": "…", "relation_type": "uses", "weight": 1.0 } ] }
```

---

## 5. Implementation checklist (`src/adapters/api/`)

```
src/adapters/api/
├── __init__.py
├── app.py        # create_app() + lifespan (engine + daemon) + uvicorn main()
├── deps.py       # set_dependencies(engine) / get_engine() / get_store() / optional bearer guard
├── models.py     # Pydantic request/response models (port the reusable ones from telegram/models.py, drop TelegramUser)
├── commands.py   # POST handlers (ask/brainstorm/research/feedback)
├── queries.py    # GET handlers (stats/interests/knowledge/graph/citations/runs/sessions/activity)
└── events.py     # SSE + WS handlers + _event_to_dict() (ported verbatim from telegram/handlers.py)
```

Reused as-is from the deleted Telegram adapter:
- `_event_to_dict()` and the SSE/WS streaming loops (`handlers.py:188–294`).
- Request models `AskRequest`, `BrainstormRequest`, `ResearchRequest`, `FeedbackRequest`,
  `EventUpdate`, `HealthResponse` (`models.py`).

Dropped entirely:
- `auth.py` (`TelegramInitDataValidator`), `bot.py` (`TelegramBotHandler`),
  `TelegramUser`, the `X-Telegram-Init-Data` header dependency, and the
  `PrivateNetworkAccessMiddleware`.

Add a CLI entry so the desktop app can spawn it: `pa serve [--host --port]` in
`src/adapters/cli/app.py`, calling `src.adapters.api.app:main`.

---

## 6. Quick start (once implemented)

```bash
poetry run python -m src.adapters.api        # serves 127.0.0.1:8787 (REST + SSE + WS + daemon)
curl http://127.0.0.1:8787/api/health
curl http://127.0.0.1:8787/api/interests?min_strength=0.3
```

The Tauri app points `VITE_API_URL` (or a Tauri config value) at
`http://127.0.0.1:8787`. See the desktop repo's `docs/API_INTEGRATION.md`.
