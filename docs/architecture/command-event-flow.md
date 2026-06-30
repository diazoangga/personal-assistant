# Command / Event Flow

Every user action is an immutable **Command**; every result is an **Event**. The engine is
the only thing that maps one to the other, which is what lets the CLI and the web API share
it unchanged.

## The contract

```python
# core/commands.py — all frozen dataclasses, all carry `user`
@dataclass(frozen=True)
class Ask(Command):            query: str
@dataclass(frozen=True)
class ResearchTopic(Command):  topic: str; depth: Literal["shallow","normal","deep"] = "normal"
# … Brainstorm, ShowInterests, ShowGraph, Opportunities, ShowDigest,
#   Feedback, IngestNow, JobStatus, Cancel, SetPref, Topics, Sources

# core/events.py — streamed back per job_id
Started(job_id, kind)
Progress(job_id, phase, message, pct?)
Message(job_id, role, text, citations[])
Result(job_id, ok, payload)        # terminal
```

## Flow

```
submit(cmd)
  ├─ job_id = uuid4()[:8]
  ├─ handler = _route(cmd)              # type(cmd) → _handle_* coroutine
  ├─ JobQueue.spawn(Job, handler(job_id, cmd))
  ├─ EventBus.publish(Started(job_id, kind))
  └─ return job_id                      # immediately; work runs async

handler(job_id, cmd):
  ├─ look up the agent/store it needs (raises if not initialized)
  ├─ do the work, publishing Progress/Message as it goes
  └─ publish Result(ok=…, payload=…)    # always terminal, even on error

events(job_id) → EventBus.subscribe(job_id)   # async iterator of Events
```

`Engine._route` (`core/engine.py`) is a plain dict from command class to handler:

| Command | Handler | Delegates to |
|---|---|---|
| `Ask` | `_handle_ask` | Brainstorming Agent `.answer()` |
| `Brainstorm` | `_handle_brainstorm` | Brainstorming Agent `.run_session()` |
| `ResearchTopic` | `_handle_research` | Research Agent `.research()` |
| `ShowInterests` | `_handle_interests` | Interest Agent |
| `ShowGraph` | `_handle_graph` | store `.relevant_subgraphs()` |
| `Opportunities` / `ShowDigest` | `_handle_opportunities` / `_handle_digest` | Opportunity Agent *(not yet registered → error)* |
| `Feedback` / `SetPref` / `Topics` / `Sources` | `_handle_*` | memory / ingest |
| `JobStatus` / `Cancel` | `_handle_status` / `_handle_cancel` | `JobQueue` |
| *unknown* | `_handle_unknown` | `Result(ok=False)` |

Handlers never raise to the caller: each wraps its body in `try/except` and turns failure
into `Result(ok=False, payload={"error": …})`. That keeps a misbehaving agent from killing
the job loop.

## EventBus

`core/bus.py` is a per-`job_id` async pub/sub. A subscriber gets an async iterator that
yields events until the terminal `Result`. The CLI subscribes directly; the web API wraps
this in an `EventHub` (`adapters/api/hub.py`) that **buffers from job creation**, so an HTTP
client can connect any time after the POST returns and still replay the whole history then
follow live — see [api/streaming.md](../api/streaming.md).

## Why this shape

A single in-process bus (no Celery/Redis) is enough because this is a single-user local
app. The Command/Event split is the seam that makes the engine reusable across transports
and testable without a network — see [ADR-0001](decisions/0001-command-event-architecture.md).

---

> **Source of truth:** `src/core/engine.py`, `src/core/commands.py`, `src/core/events.py`,
> `src/core/bus.py`, `src/core/jobs.py`.
