# ADR-0001: Command / Event architecture

**Status:** Accepted · **Date:** 2026-06 (retroactive)

## Context

The assistant needs to be driven from multiple front-ends (a CLI today, a local web API
for the desktop app, potentially Slack) and to run long-lived work (research) whose
progress the user watches. We did not want two copies of the orchestration logic, one per
transport, nor a heavyweight task broker for a single-user local app.

## Decision

All user actions are immutable **Command** dataclasses (`core/commands.py`). A single
interface-agnostic **Engine** (`core/engine.py`) maps each command type to a handler
coroutine and streams results back as **Event**s over an in-process **EventBus**
(`core/bus.py`). `submit(cmd)` returns a `job_id` immediately; events are consumed
asynchronously. No external broker (Celery/Redis) — `JobQueue` tracks `asyncio` tasks.

## Consequences

- **+** CLI and FastAPI adapters share the engine verbatim; the API only adds an
  `EventHub` buffer on top of the bus.
- **+** Handlers are unit-testable without a network; commands are trivially serialisable.
- **+** Adding a feature = add a frozen command + a `_handle_*` + one route line.
- **−** No durability: jobs live in memory, so a process restart loses in-flight work.
  Acceptable for a local single-user tool; would need a broker for multi-user/server use.
- **−** Back-pressure and cancellation are hand-rolled in `JobQueue` rather than provided
  by a framework.
