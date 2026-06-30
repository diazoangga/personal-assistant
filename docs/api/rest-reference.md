# Local Web API — REST Reference

The FastAPI app (`adapters/api/`) is the backend for the Tauri desktop client. It binds
**loopback only** (`127.0.0.1:8787`), runs the **engine and daemon in one process** sharing
one knowledge store, and exposes two families of routes:

- **Commands** — `POST` an action, get a `job_id`, stream the result (see
  [streaming.md](streaming.md)).
- **Queries** — synchronous dashboard reads straight from the store.

All routes are under `/api`. Interactive docs at `/docs`.

## Auth & identity

- Optional bearer: if `LOCAL_API_TOKEN` is set, every route requires
  `Authorization: Bearer <token>` (enforced by `require_auth`). If unset, auth is open
  (loopback only).
- Single user: `LOCAL_API_USER` (default `local`) is stamped server-side; there is no
  login. CORS allows the Tauri/Vite dev origins only.

## Commands (POST → job)

| Method | Path | Body | Result |
|---|---|---|---|
| `POST` | `/api/ask` | `{query, session_id?}` | job; streams `message` (answer + citations) then `result`. `result_extra` adds `{session_id}`. |
| `POST` | `/api/brainstorm` | `{text, session_id?}` | job; ideation answer streams as `message` + `result`. |
| `POST` | `/api/research` | `{topic, depth}` | job; `depth` is `shallow\|normal\|deep` or int 1–5 (1–2→shallow, 3→normal, 4–5→deep). `result_extra` adds run deltas (`papers_found`, `papers_new`, `concepts_extracted`, `concepts_new`, `relationships_found`, `run_id`). |
| `POST` | `/api/feedback` | `{ref, verdict, note?}` | job; `verdict` ∈ `accept\|reject\|correct`; persisted to `activity_log`. |

All four return `JobStarted { job_id, kind }` immediately and run the work as an asyncio
task that drives the engine's public coroutine (which carries the conversation/knowledge
side effects). The job is registered in the `EventHub` **before** work starts, so a client
can stream from `job_id` without a race.

## Queries (synchronous reads)

| Method | Path | Query params | Returns |
|---|---|---|---|
| `GET` | `/api/health` | — | `{status, version}` |
| `GET` | `/api/daemon/status` | — | `{running, pid, last_ingest}` |
| `GET` | `/api/stats` | — | counts: interests/concepts/citations + `knowledge_entries`, `total_questions` |
| `GET` | `/api/interests` | `min_strength` (0–1) | interest rows |
| `GET` | `/api/interests/{label}/timeline` | `limit` | evidence rows (`signal_id, topic, confidence, timestamp`) |
| `GET` | `/api/knowledge` | `min_quality` (def 0.65), `limit` | high-quality Q&A entries |
| `GET` | `/api/knowledge/search` | `q`, `limit` | text search over entries |
| `GET` | `/api/graph/subgraph` | `topic?`, `depth` (1–4, def 2) | `{nodes, edges}` from `relevant_subgraphs` |
| `GET` | `/api/citations/{id}` | — | citation + `linked_concepts` (404 if unknown) |
| `GET` | `/api/research/runs` | `topic?`, `limit` | research run log |
| `GET` | `/api/sessions` | `limit` | conversation sessions |
| `GET` | `/api/sessions/{id}/turns` | `limit` | turns for a session |
| `GET` | `/api/activity` | `limit` | `activity_log` rows (daemon input feed) |

Query handlers read committed state directly via the store (`get_*` methods or
`store._db.fetchall/fetchone`); no jobs, no streaming.

## Running it

```bash
poetry run python -m src.adapters.api          # serves 127.0.0.1:8787
# env: LOCAL_API_HOST, LOCAL_API_PORT, LOCAL_API_TOKEN, LOCAL_API_USER
```

The desktop client's consumption of these routes is documented in
`personal-assistant-desktop/docs/architecture/api-client.md`.

---

> **Source of truth:** `src/adapters/api/{queries,commands,models,deps,app}.py`.
