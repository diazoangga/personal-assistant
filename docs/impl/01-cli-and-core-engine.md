---
title: "Implementation: CLI & Core Engine"
created: 2026-06-20
updated: 2026-06-20
version: 1.0.0
status: Draft
tags: [implementation, core, cli]
related:
  - ../personal-assistant.plans.md
  - ../personal-assistant.implementation.md
---

> Whenever this documentation file changes, update the `updated` field and append a new entry to `changelog` describing the revision.

# Implementation: CLI & Core Engine

The Core Engine is the interface-agnostic heart of the system. The CLI is the
first adapter built on it. This doc defines the engine's contracts and the CLI's
thin mapping onto them. The Slack adapter (next doc) renders the *same* contracts.

> **Design rule (D2):** an adapter may only (1) build a `Command`, (2) submit it,
> (3) render the resulting `Event` stream. No agent logic, no storage access, no
> model calls in an adapter.

---

## 1. The Command / Event Contract

Everything flows through two value types. Adapters speak `Command` in, `Event` out.

```python
# pa/core/commands.py
from dataclasses import dataclass

@dataclass(frozen=True)
class Command:
    user: str            # who issued it (cli-local user or slack user id)

@dataclass(frozen=True)
class Build(Command):
    idea: str
    auto_approve: bool = False     # skip HITL gates

@dataclass(frozen=True)
class ResearchNow(Command): pass

@dataclass(frozen=True)
class Ask(Command):
    query: str

@dataclass(frozen=True)
class ShowDigest(Command):
    date: str | None = None

@dataclass(frozen=True)
class JobStatus(Command):
    job_id: str | None = None

@dataclass(frozen=True)
class Approve(Command):
    job_id: str

@dataclass(frozen=True)
class Cancel(Command):
    job_id: str

@dataclass(frozen=True)
class SetPref(Command):
    key: str
    value: str

@dataclass(frozen=True)
class Topics(Command):
    action: str          # add | list | rm
    name: str | None = None
```

```python
# pa/core/events.py
from dataclasses import dataclass, field

@dataclass(frozen=True)
class Event:
    job_id: str

@dataclass(frozen=True)
class Started(Event):
    kind: str            # "build" | "research" | ...

@dataclass(frozen=True)
class Progress(Event):
    phase: str           # "research" | "architect" | "developer"
    message: str
    pct: float | None = None

@dataclass(frozen=True)
class ApprovalNeeded(Event):
    phase: str
    preview: str         # markdown the user reviews before continuing

@dataclass(frozen=True)
class Result(Event):
    ok: bool
    payload: dict = field(default_factory=dict)   # e.g. {"repo": "...", "report": "..."}
```

> Adding a feature = add a `Command` subtype, handle it in the engine, render its
> `Event`s in each adapter. The contract is the extension point.

---

## 2. The Engine

The engine owns a Job Queue and an in-process event bus. `submit` enqueues work and
returns immediately (async, non-blocking — required so Slack can ack in < 3s).

```python
# pa/core/engine.py
import asyncio, uuid
from typing import AsyncIterator
from .commands import Command, Build, ResearchNow, Ask, Approve, JobStatus
from .events import Event, Started, Result
from .bus import EventBus
from .jobs import JobQueue, Job

class Engine:
    def __init__(self, *, agents, research, knowledge, memory):
        self._bus = EventBus()
        self._jobs = JobQueue()
        self._agents = agents          # meta-agent graph + workers
        self._research = research       # daily research loop
        self._knowledge = knowledge     # vector + memory access
        self._memory = memory

    async def submit(self, cmd: Command) -> str:
        job_id = uuid.uuid4().hex[:8]
        handler = self._route(cmd)               # pick coroutine for this command
        self._jobs.spawn(Job(job_id, cmd), handler(job_id, cmd))
        await self._bus.publish(Started(job_id, kind=cmd.__class__.__name__.lower()))
        return job_id

    def events(self, job_id: str) -> AsyncIterator[Event]:
        return self._bus.subscribe(job_id)

    # internal: map a Command to the coroutine that fulfills it
    def _route(self, cmd: Command):
        return {
            Build:        self._handle_build,
            ResearchNow:  self._handle_research,
            Ask:          self._handle_ask,
            Approve:      self._handle_approve,
            JobStatus:    self._handle_status,
        }[type(cmd)]

    async def _handle_build(self, job_id: str, cmd: Build):
        # delegate to the LangGraph Meta-Agent; it publishes Progress/ApprovalNeeded
        result = await self._agents.run_build(job_id, cmd, publish=self._bus.publish)
        await self._bus.publish(Result(job_id, ok=result.ok, payload=result.payload))

    async def _handle_ask(self, job_id: str, cmd: Ask):
        answer = await self._knowledge.answer(cmd.query)   # hybrid RAG + citations
        await self._bus.publish(Result(job_id, ok=True, payload=answer))
    # … _handle_research, _handle_approve, _handle_status
```

`bus.py` is a minimal async pub/sub keyed by `job_id` (an `asyncio.Queue` per
subscriber). `jobs.py` tracks `{job_id: state}` for `pa status`, supports cancel
(`task.cancel()`), and persists a row to Persistent Memory so status survives a
restart. Keep both small; they're plumbing, not product.

---

## 3. Human-in-the-Loop Gates

When the Meta-Agent reaches a gate it publishes `ApprovalNeeded` and *parks* the
job (awaits an `asyncio.Event` stored on the Job). The user replies via either
interface:

```
pa approve <job>      ── or ──   Slack "Approve" button
        │                              │
        └──────── Approve(job_id) ─────┘
                       │
              engine sets job.approval_event → graph resumes
```

Because the gate is resolved by a `Command`, it is interface-symmetric for free:
approve from your phone what you started at your desk.

---

## 4. The CLI Adapter

Typer for commands, Rich for live rendering. The whole adapter is a dispatch table
plus an event renderer.

```python
# pa/adapters/cli/app.py
import asyncio, typer
from rich.live import Live
from pa.core import build_engine          # wires deps, returns Engine
from pa.core.commands import Build, Ask, JobStatus, Approve, ResearchNow

app = typer.Typer(help="pa — your local personal assistant")

def _run(cmd):
    async def main():
        engine = build_engine()
        job_id = await engine.submit(cmd)
        with Live() as live:
            async for ev in engine.events(job_id):
                live.update(render(ev))      # Progress/ApprovalNeeded/Result → Rich
                if isinstance(ev, Result):
                    break
    asyncio.run(main())

@app.command()
def build(idea: str, yes: bool = typer.Option(False, "--yes", help="auto-approve gates")):
    """Run the SDLC pipeline on an idea."""
    _run(Build(user="local", idea=idea, auto_approve=yes))

@app.command()
def ask(query: str):
    """Query the knowledge base (agentic RAG, with citations)."""
    _run(Ask(user="local", query=query))

@app.command()
def status(job: str = typer.Argument(None)):
    _run(JobStatus(user="local", job_id=job))

@app.command()
def approve(job: str):
    _run(Approve(user="local", job_id=job))

research = typer.Typer()
app.add_typer(research, name="research")

@research.command("now")
def research_now():
    _run(ResearchNow(user="local"))
```

`render(event)` is the only CLI-specific presentation logic:

| Event | CLI rendering |
|-------|---------------|
| `Started` | spinner + `job <id> started` |
| `Progress` | phase label + message, optional progress bar |
| `ApprovalNeeded` | print `preview`, then `Approve? run: pa approve <job>` (or prompt inline) |
| `Result(ok=True)` | green summary + path/repo + key artifacts |
| `Result(ok=False)` | red error + pointer to `pa status <job>` log |

The Slack adapter implements the same table with Block Kit instead of Rich —
that's the *entire* difference between the two interfaces.

---

## 5. Command ↔ CLI ↔ Slack Map (parity check)

Keep this table green; it's the acceptance test for D2.

| Command | CLI | Slack | Engine handler |
|---------|-----|-------|----------------|
| `Build` | `pa build "<idea>"` | `/build <idea>` | `_handle_build` |
| `ResearchNow` | `pa research now` | `/research` | `_handle_research` |
| `ShowDigest` | `pa digest [date]` | `/digest` | `_handle_digest` |
| `Ask` | `pa ask "<q>"` | `/ask <q>` | `_handle_ask` |
| `JobStatus` | `pa status [job]` | `/status` | `_handle_status` |
| `Approve` | `pa approve <job>` | button / `/approve` | `_handle_approve` |
| `Cancel` | `pa cancel <job>` | `/cancel <job>` | `_handle_cancel` |
| `SetPref` | `pa config set k v` | `/prefs set k v` | `_handle_setpref` |
| `Topics` | `pa topics add/list/rm` | `/topics …` | `_handle_topics` |

---

## 6. Testing

- **Contract tests:** construct each `Command`, submit to an engine with stubbed
  agents, assert the expected `Event` sequence.
- **Parity test:** a table-driven test that asserts every `Command` has both a CLI
  binding and a Slack binding (import both dispatch tables, diff the key sets).
- **Renderer tests:** feed a canned event stream to `render()` and snapshot output.

---

## Related
- [../personal-assistant.implementation.md](../personal-assistant.implementation.md)
- [02-slack-gateway.md](02-slack-gateway.md)
- [05-meta-agent-and-skills.md](05-meta-agent-and-skills.md)
