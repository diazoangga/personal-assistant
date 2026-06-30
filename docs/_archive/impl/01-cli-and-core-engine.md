---
title: "Implementation: CLI & Core Engine"
created: 2026-06-20
updated: 2026-06-21
version: 3.0.0
status: Draft
tags: [implementation, core, cli]
changelog:
  - version: 1.0.0
    date: 2026-06-20
    changes: "Initial Command/Event engine + CLI for the SDLC builder"
  - version: 2.0.0
    date: 2026-06-21
    changes: >-
      Updated command set for the cognitive engine. Replaced Build/Approve with
      Ask/Brainstorm/Interests/Opportunities/Feedback/IngestNow; added a Message
      event and brainstorm REPL; refreshed the parity table.
  - version: 3.0.0
    date: 2026-06-21
    changes: >-
      Added `ResearchTopic` (manual Research Agent trigger) and `ShowGraph`
      (citation/knowledge graph view) commands, plus `pa research` / `pa graph
      show` CLI bindings. Brainstorm is now bound to a full Brainstorming Agent,
      not a Meta Agent mode — no contract change, just a corrected reference.
related:
  - ../personal-assistant.plans.md
  - ../personal-assistant.implementation.md
---

> Whenever this documentation file changes, update the `updated` field and append a new entry to `changelog` describing the revision.

# Implementation: CLI & Core Engine

The Core Engine is the interface-agnostic heart. The CLI is the first adapter built
on it; the Slack adapter (next doc) renders the *same* contracts.

> **Design rule (D2):** an adapter may only (1) build a `Command`, (2) submit it,
> (3) render the resulting `Event` stream. No agent logic, no storage access, no
> model calls in an adapter.

---

## 1. The Command / Event Contract

Everything flows through two value types. Adapters speak `Command` in, `Event` out.

```python
# src/core/commands.py
from dataclasses import dataclass

@dataclass(frozen=True)
class Command:
    user: str                # cli-local user or slack user id

@dataclass(frozen=True)
class Ask(Command):                  # one-shot, cited Q&A over the KB
    query: str

@dataclass(frozen=True)
class Brainstorm(Command):           # interactive, multi-turn session
    text: str
    session_id: str | None = None

@dataclass(frozen=True)
class ShowInterests(Command):
    view: str = "show"               # show | timeline

@dataclass(frozen=True)
class ResearchTopic(Command):        # manual Research Agent trigger
    topic: str
    depth: str = "normal"            # shallow | normal | deep

@dataclass(frozen=True)
class ShowGraph(Command):            # view the citation/knowledge graph
    kind: str = "knowledge"          # knowledge | citation
    topic: str | None = None

@dataclass(frozen=True)
class Opportunities(Command):
    action: str = "list"             # list | save | dismiss
    ref: str | None = None

@dataclass(frozen=True)
class ShowDigest(Command):
    date: str | None = None

@dataclass(frozen=True)
class Feedback(Command):
    ref: str                         # opportunity/answer id
    verdict: str                     # accept | reject | correct
    note: str | None = None

@dataclass(frozen=True)
class IngestNow(Command):
    connector: str | None = None     # all enabled if None

@dataclass(frozen=True)
class JobStatus(Command):
    job_id: str | None = None

@dataclass(frozen=True)
class Cancel(Command):
    job_id: str

@dataclass(frozen=True)
class SetPref(Command):
    key: str; value: str

@dataclass(frozen=True)
class Topics(Command):
    action: str; name: str | None = None    # add | list | rm

@dataclass(frozen=True)
class Sources(Command):
    action: str; name: str | None = None    # add | list | rm  (connectors)
```

```python
# src/core/events.py
from dataclasses import dataclass, field

@dataclass(frozen=True)
class Event:
    job_id: str

@dataclass(frozen=True)
class Started(Event):
    kind: str

@dataclass(frozen=True)
class Progress(Event):
    phase: str; message: str; pct: float | None = None

@dataclass(frozen=True)
class Message(Event):                 # a brainstorm/ask turn
    role: str                         # "assistant"
    text: str
    citations: list[str] = field(default_factory=list)

@dataclass(frozen=True)
class Result(Event):
    ok: bool
    payload: dict = field(default_factory=dict)
```

> Adding a feature = add a `Command` subtype, handle it in the engine, render its
> `Event`s in each adapter. The contract is the extension point.

---

## 2. The Engine

The engine owns a Job Queue and an in-process event bus. `submit` enqueues work and
returns immediately (async — required so Slack can ack in < 3s). It also runs the
schedulers for the three loops (sensing / understanding / insight).

```python
# src/core/engine.py
import uuid
from typing import AsyncIterator
from .commands import Command, Ask, Brainstorm, Opportunities, IngestNow, Feedback, JobStatus, ResearchTopic, ShowGraph
from .events import Event, Started, Result, Message
from .bus import EventBus
from .jobs import JobQueue, Job

class Engine:
    def __init__(self, *, agents, ingest, store, memory, graph):
        self._bus = EventBus()
        self._jobs = JobQueue()
        self._agents = agents          # meta graph + interest + research + opportunity + brainstorm
        self._ingest = ingest          # activity sensing pipeline
        self._store = store            # vector KB
        self._memory = memory          # SQLite user model
        self._graph = graph            # SQLite graph store (citation + knowledge)

    async def submit(self, cmd: Command) -> str:
        job_id = uuid.uuid4().hex[:8]
        handler = self._route(cmd)
        self._jobs.spawn(Job(job_id, cmd), handler(job_id, cmd))
        await self._bus.publish(Started(job_id, kind=cmd.__class__.__name__.lower()))
        return job_id

    def events(self, job_id: str) -> AsyncIterator[Event]:
        return self._bus.subscribe(job_id)

    def _route(self, cmd: Command):
        return {
            Ask:           self._handle_ask,
            Brainstorm:    self._handle_brainstorm,
            ResearchTopic: self._handle_research,
            ShowGraph:     self._handle_graph,
            Opportunities: self._handle_opportunities,
            IngestNow:     self._handle_ingest,
            Feedback:      self._handle_feedback,
            JobStatus:     self._handle_status,
        }[type(cmd)]

    async def _handle_ask(self, job_id, cmd: Ask):
        ans = await self._agents.answer(cmd.query)         # hybrid RAG + citations
        await self._bus.publish(Message(job_id, role="assistant",
                                        text=ans.text, citations=ans.citations))
        await self._bus.publish(Result(job_id, ok=True, payload={"answer": ans.text}))

    async def _handle_brainstorm(self, job_id, cmd: Brainstorm):
        # runs the Brainstorming Agent's session graph; streams Message turns (see 06/brainstorm doc)
        await self._agents.brainstorm(job_id, cmd, publish=self._bus.publish)

    async def _handle_research(self, job_id, cmd: ResearchTopic):
        # manual trigger — same Research Agent path an Interest classification uses
        findings = await self._agents.research(cmd.topic, depth=cmd.depth, publish=self._bus.publish)
        await self._bus.publish(Result(job_id, ok=True, payload={"summary": findings.summary}))

    async def _handle_graph(self, job_id, cmd: ShowGraph):
        subgraph = await self._graph.relevant_subgraphs([cmd.topic] if cmd.topic else None)
        await self._bus.publish(Result(job_id, ok=True, payload={"graph": subgraph}))

    async def _handle_feedback(self, job_id, cmd: Feedback):
        self._memory.record_feedback(cmd)                  # feeds Meta Agent learning
        await self._bus.publish(Result(job_id, ok=True))
    # … _handle_opportunities, _handle_ingest, _handle_status
```

`bus.py` is a minimal async pub/sub keyed by `job_id`. `jobs.py` tracks
`{job_id: state}` for `pa status`, supports cancel, and persists a row to Memory so
status survives a restart. Keep both small; they're plumbing.

---

## 3. Interactive Sessions (Brainstorm)

Brainstorm is multi-turn. A session keeps a `session_id`; each user turn is a new
`Brainstorm(text, session_id)` command, and the engine streams `Message` events back.
The session graph (the **Brainstorming Agent** — a full agent, not a Meta Agent
mode) is checkpointed so it resumes across turns and restarts — see
[../personal-assistant.brainstorm-feature.md](../personal-assistant.brainstorm-feature.md).
Mid-session, the Brainstorming Agent can itself submit a `ResearchTopic` command to
the engine if it decides KB coverage is too thin ("research this, then propose").

```
pa brainstorm                          Slack: a thread
   │  (REPL: each line → Brainstorm)      │  (each reply → Brainstorm, thread_ts = session)
   └──────────── Brainstorm(text, session_id) ───────────┘
                          │
            engine → brainstorm graph → Message turns (with citations)
```

Because a session is just repeated `Brainstorm` commands, it is interface-symmetric:
start at the desk, continue from your phone.

---

## 4. The CLI Adapter

Typer for commands, Rich for live rendering. The adapter is a dispatch table plus an
event renderer.

```python
# src/adapters/cli/app.py
import asyncio, typer
from rich.live import Live
from pa.core import build_engine
from pa.core.commands import Ask, Brainstorm, ShowInterests, Opportunities, IngestNow, JobStatus

app = typer.Typer(help="pa — your local cognitive assistant")

def _run(cmd):
    async def main():
        engine = build_engine()
        job_id = await engine.submit(cmd)
        with Live() as live:
            async for ev in engine.events(job_id):
                live.update(render(ev))
                if isinstance(ev, Result): break
    asyncio.run(main())

@app.command()
def ask(query: str):
    """Ask the knowledge base (cited)."""
    _run(Ask(user="local", query=query))

@app.command()
def brainstorm():
    """Interactive brainstorm: ask anything, or get proposals from your interests."""
    asyncio.run(_repl())               # loops: read line → submit Brainstorm → print Message turns

@app.command()
def interests(view: str = typer.Argument("show")):
    _run(ShowInterests(user="local", view=view))

@app.command()
def research(topic: str, depth: str = typer.Option("normal")):
    """Manually trigger the Research Agent for a topic (same path Interest Agent uses)."""
    _run(ResearchTopic(user="local", topic=topic, depth=depth))

graph = typer.Typer(); app.add_typer(graph, name="graph")
@graph.command("show")
def graph_show(kind: str = typer.Option("knowledge"), topic: str = typer.Option(None)):
    _run(ShowGraph(user="local", kind=kind, topic=topic))

@app.command()
def opportunities(action: str = typer.Argument("list"), ref: str = typer.Argument(None)):
    _run(Opportunities(user="local", action=action, ref=ref))

@app.command()
def digest(date: str = typer.Argument(None)):
    _run(ShowDigest(user="local", date=date))

ingest = typer.Typer(); app.add_typer(ingest, name="ingest")
@ingest.command("now")
def ingest_now(connector: str = typer.Argument(None)):
    _run(IngestNow(user="local", connector=connector))
```

`render(event)` is the only CLI-specific presentation logic:

| Event | CLI rendering |
|-------|---------------|
| `Started` | spinner + `job <id> started` |
| `Progress` | phase label + message, optional bar |
| `Message` | assistant text + a footnote list of `citations` |
| `Result(ok=True)` | green summary (e.g. opportunity list, saved id) |
| `Result(ok=False)` | red error + `pa status <job>` pointer |

The Slack adapter implements the same table with Block Kit — that's the *entire*
difference between the interfaces.

---

## 5. Command ↔ CLI ↔ Slack Map (parity check)

Keep this table green; it's the acceptance test for D2.

| Command | CLI | Slack | Engine handler |
|---------|-----|-------|----------------|
| `Ask` | `pa ask "<q>"` | `/ask <q>` | `_handle_ask` |
| `Brainstorm` | `pa brainstorm` (REPL) | thread replies | `_handle_brainstorm` |
| `ShowInterests` | `pa interests [show\|timeline]` | `/interests` | `_handle_interests` |
| `ResearchTopic` | `pa research <topic> [--depth]` | `/research <topic>` | `_handle_research` |
| `ShowGraph` | `pa graph show [--kind] [--topic]` | `/graph [knowledge\|citation] [topic]` | `_handle_graph` |
| `Opportunities` | `pa opportunities list\|save\|dismiss` | `/opps …` / buttons | `_handle_opportunities` |
| `ShowDigest` | `pa digest [date]` | `/digest` | `_handle_digest` |
| `Feedback` | `pa feedback <ref> <verdict>` | 👍/👎 buttons | `_handle_feedback` |
| `IngestNow` | `pa ingest now [connector]` | `/ingest` | `_handle_ingest` |
| `JobStatus` | `pa status [job]` | `/status` | `_handle_status` |
| `Cancel` | `pa cancel <job>` | `/cancel <job>` | `_handle_cancel` |
| `SetPref` | `pa config set k v` | `/prefs set k v` | `_handle_setpref` |
| `Topics` | `pa topics add/list/rm` | `/topics …` | `_handle_topics` |
| `Sources` | `pa sources add/list/rm` | `/sources …` | `_handle_sources` |

---

## 6. Testing

- **Contract tests:** construct each `Command`, submit to an engine with stubbed
  agents, assert the expected `Event` sequence (incl. `Message` turns for brainstorm).
- **Parity test:** assert every `Command` has both a CLI and a Slack binding (diff
  the dispatch-table key sets).
- **Renderer tests:** feed a canned event stream to `render()` and snapshot output.

---

## Related
- [../personal-assistant.implementation.md](../personal-assistant.implementation.md)
- [02-slack-gateway.md](02-slack-gateway.md)
- [05-meta-agent-and-skills.md](05-meta-agent-and-skills.md)
- [06-research-agent.md](06-research-agent.md) — what `ResearchTopic` triggers
