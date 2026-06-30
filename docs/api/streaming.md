# Local Web API — Streaming (SSE + WebSocket)

Command endpoints return a `job_id`; the work runs asynchronously and its progress streams
over **Server-Sent Events** or a **WebSocket**. Both read from the same `EventHub`.

## Endpoints

| Transport | Path | Notes |
|---|---|---|
| SSE | `GET /api/events/{job_id}` | `text/event-stream`; `data: <json>\n\n` frames |
| WebSocket | `WS /api/ws/events/{job_id}` | preferred for live updates; `send_json` per event |

Unknown `job_id` → a single `error` event (`{message: "unknown job"}`) then close.

## The EventHub buffers from creation

`adapters/api/hub.py` wraps the engine's `EventBus`. When a command endpoint creates a job,
the hub starts **buffering that job's events immediately**. So a client may connect any time
after the POST returns and still receive the full history, then follow live updates until
the terminal `result`. This removes the connect-race between "POST returned" and "open the
stream".

## Event envelope

Every streamed event is the same JSON envelope:

```json
{ "event_type": "started|progress|message|result|error",
  "job_id": "ab12cd34",
  "payload": { } }
```

| `event_type` | `payload` |
|---|---|
| `started` | `{ kind }` |
| `progress` | `{ phase, message, pct? }` |
| `message` | `{ role, text, citations[] }` (ask/brainstorm answers) |
| `result` | `{ ok, ... }` — **terminal**; stream closes after this |
| `error` | `{ message }` |

This mirrors the engine's `core/events.py` types (`Started`, `Progress`, `Message`,
`Result`), flattened to an envelope by `hub.run_text_job`.

## Lifecycle of a streamed command

```
POST /api/research {topic, depth}
  → hub.create("research") → job_id          (buffering starts)
  → asyncio.create_task(run_text_job(...))    (drives engine.research)
  → 200 { job_id, kind }
client: WS /api/ws/events/{job_id}
  ← started → progress×N → result(ok, deltas) ← stream closes
```

On the FE side, the terminal `result` is the cue to invalidate cached dashboard queries
(stats/interests/graph) so they reflect what the run produced — see the desktop
`architecture/api-client.md`.

---

> **Source of truth:** `src/adapters/api/streams.py`, `src/adapters/api/hub.py`,
> `src/core/events.py`.
