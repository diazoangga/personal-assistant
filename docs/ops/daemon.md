# Daemon

`PersonalAssistantDaemon` (`daemon/service.py`) is the 24/7 background process that makes
the assistant proactive: it polls connectors, runs new activity through the Interest Agent,
and submits the research triggers that come back.

## The loop

```
run():
  every check_interval_seconds (default 60):
    if elapsed since last ingest ≥ ingest_interval_minutes (default 15):
        _run_ingest_cycle()
    _check_connectors()        # placeholder for realtime sources

_run_ingest_cycle():
  signals = []
  for connector in get_enabled_connectors():
      signals += await connector.fetch(since=last_ingest)
  topics = await engine.process_activity_signals(signals)   # Interest Agent
  for t in topics:
      job_id = await engine.submit(t)                       # ResearchTopic → Research Agent
```

So the daemon is the bridge between [connectors](../connectors/connector-contract.md) and
the [signal flow](../architecture/signal-flow.md): fetch → classify → trigger → research.

## Two ways it runs

| Mode | How | Notes |
|---|---|---|
| **In-process (with the API)** | `adapters/api/app.py` starts the daemon as an asyncio task in the API's lifespan, sharing the engine + store. | This is the desktop setup — one process serves API *and* senses. |
| **Standalone** | `pa daemon start` / `python -m src.daemon.service` | Writes a PID file; `pa daemon stop` / `logs`. |

`/api/daemon/status` reports `running` and `last_ingest` from the in-process daemon.

## Connectors

`_initialize_connectors()` registers connectors per `[connectors.*]` config: **GitHub**
(enabled by default), **Slack** and **Browser** (opt-in). Failures to initialise a
connector are logged and skipped, not fatal.

## Config (`[daemon]`)

| Key | Default | Meaning |
|---|---|---|
| `check_interval_seconds` | 60 | loop tick |
| `ingest_interval_minutes` | 15 | full ingest cadence |
| `log_level` | INFO | DEBUG surfaces classification + trigger lines |
| `log_file` | `./data/daemon.log` | |
| `pid_file` / `state_file` | `./data/daemon.pid` / `daemon_state.json` | standalone mode |

## Debugging

```bash
poetry run pa daemon logs -f       # or: tail -f data/daemon.log
```

Grep the log for `Classified … →` (classification), `Research trigger:` (threshold
crossed), and `Research trigger submitted` (command queued).

---

> **Source of truth:** `src/daemon/service.py`, `src/daemon/manager.py`,
> `src/adapters/api/app.py` (lifespan).
