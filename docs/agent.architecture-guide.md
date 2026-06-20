---
title: Agent Architecture & Development Guide
created: 2026-06-20
updated: 2026-06-20
version: 1.0.0
status: Draft
tags: [architecture, agents, guide, contributing]
related:
  - personal-assistant.plans.md
  - personal-assistant.implementation.md
---

> Whenever this documentation file changes, update the `updated` field and append a new entry to `changelog` describing the revision.

# Agent Architecture & Development Guide

This is the guide for *working on* the assistant: how the layers fit, the rules
that keep them decoupled, and step-by-step recipes for the common extensions
(adding a command, an interface, an agent, a research source, a skill). Read the
[plan](personal-assistant.plans.md) and
[implementation roadmap](personal-assistant.implementation.md) first for the *what*;
this is the *how to change it*.

---

## 1. The Layer Model (and the one rule)

```
Interface Adapters  (CLI, Slack)        ← presentation only
        │ Command ↓        ↑ Event
Core Engine          (bus, jobs, queue) ← orchestration glue
        │
Agents               (meta + workers)   ← reasoning
        │
Infrastructure       (Ollama, vector, memory, sources) ← capabilities
```

**The one rule:** dependencies point *downward only*. An adapter may import the
Core Engine; the Core Engine must never import an adapter. Agents may use
infrastructure; infrastructure never imports agents. If you need an upward call,
invert it with an event or a callback (`publish`) passed in — never an import.

This rule is what makes CLI/Slack parity (D2) and the future cloud-worker swap (D1
escape hatch) cheap instead of painful.

---

## 2. The Two Contracts You Must Not Break

Everything composes through `Command` (down) and `Event` (up), defined in
[impl/01-cli-and-core-engine.md](impl/01-cli-and-core-engine.md). Treat them as the
public API of the system:

- **Adapters** translate user input ⇄ `Command`/`Event`. Nothing else.
- **Engine** maps each `Command` to a handler and emits `Event`s.
- **Agents/infra** never see a `Command` or an interface — they receive plain typed
  arguments and return plain typed results.

If a change requires editing an adapter *and* an agent for one feature, you've
probably leaked logic across a layer. Push it down into the engine/agents and have
the adapter just render the result.

---

## 3. Agent Design Principles

1. **One job per agent.** Research evaluates feasibility; Architect designs;
   Developer builds. Don't merge roles — separation is what keeps each prompt small
   and each context clean.
2. **Minimal context in.** Pass an agent only its phase input. The Vector DB exists
   to shrink context; use it. Never hand a worker the full pipeline state.
3. **Structured output out.** Each agent returns a typed artifact (report,
   blueprint, build result), not free-form chat. The next phase consumes the
   structure, not prose.
4. **Tools are the only side effects.** Reasoning happens in the model; touching
   files, storage, shell, or the web happens in a named tool. This keeps agents
   testable with stub tools.
5. **Local-first models.** Default every agent to Ollama. The model is chosen by
   *role* (small for routing, large for building) in `llm/ollama.py`, not hard-coded
   in the agent.

---

## 4. Model Routing & Compute Discipline

`llm/ollama.py` is the single place models are selected and loaded.

```python
# pa/llm/ollama.py
ROLE_MODELS = {"meta": "qwen3:8b", "worker": "qwen3-coder:30b", "embedding": "nomic-embed-text"}

class OllamaRuntime:
    async def complete(self, role: str, prompt: str, **kw) -> str: ...
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    # concurrency guard: serialize heavy loads so worker + embedding never co-load
```

Rules:
- **Never** name a model inside an agent — ask for a *role*.
- The **concurrency guard** prevents the big worker model and the embedding model
  from loading simultaneously (VRAM). The digest scheduler also respects
  `build_quiet_hours`.
- **The cloud escape hatch (D1):** if a future task genuinely needs a frontier
  model, add a role mapping to a remote backend *here only*. No agent code changes,
  because agents ask for a role, not a provider.

---

## 5. Recipes

### 5.1 Add a new command (must keep CLI/Slack parity)
1. Add a `Command` subtype in `core/commands.py`.
2. Add a handler + route entry in `core/engine.py` (emit `Progress`/`Result`).
3. Bind it in **both** adapters: `adapters/cli/app.py` and `adapters/slack/app.py`.
4. Update the parity table in [impl/01](impl/01-cli-and-core-engine.md) §5 and the
   parity test. **A command with only one binding fails CI.**

### 5.2 Add a new interface (e.g. a TUI or a REST API)
1. Create `adapters/<name>/app.py`.
2. For each shared `Command`, build it from that interface's input.
3. Render the `Event` stream in that interface's idiom.
4. Import `pa.core` only. You should not need to touch any agent or infra code —
   if you do, something leaked upward.

### 5.3 Add a new worker agent
1. Create `agents/workers/<name>.py` with a typed `run(input) -> artifact`.
2. Add a `dispatch_<name>_worker` tool in `agents/meta/tools.py`.
3. Add a node + edges in `agents/meta/graph.py`; decide its phase gate.
4. Reference it from the relevant Skill's Steps so routing stays deterministic.
5. Give it the smallest toolset that does the job; default it to the `worker` role.

### 5.4 Add a research source
1. Create `research/sources/<name>.py` implementing `Source.fetch -> list[RawItem]`.
2. Register it in the source list (config). No pipeline changes — ingest/dedup/
   chunk/embed are source-agnostic.
3. Add a record/replay fixture test.

### 5.5 Add or edit a Skill
1. Edit/create the Markdown in `~/assistant/skills/` (and seed `skills/` in-repo).
2. Keep the four sections: Trigger, Steps, Success Criteria, Failure Handling.
3. Skills are Git-tracked — review changes as diffs. Auto-proposed edits (Phase 3
   self-improvement) land as a PR/diff for human review, never auto-merge.

---

## 6. Observability & Debugging

- **`pa status <job>`** — current state, phase, and log trail (from Persistent
  Memory). The first stop for "what happened?".
- **LangGraph checkpointer** — every build run is checkpointed; replay or
  time-travel to the failing node instead of re-running the whole pipeline.
- **Run traces** — `run_traces` in Persistent Memory hold a compact post-run
  summary (outcome + lessons), feeding both debugging and skill self-improvement.
- **Structured logs** — agents log tool calls and I/O sizes; watch context size per
  phase to catch creeping context bloat early (the #1 local-model killer).

---

## 7. Definition of Done (mirror of the roadmap)

A change is done when it is: driven by a `Command`, reachable from both CLI and
Slack (if user-facing), emits `Progress` + a final `Result`, inspectable via
`pa status`, and covered by at least a stub-model smoke test. See
[implementation roadmap §7](personal-assistant.implementation.md).

---

## 8. Common Anti-Patterns (don't)

| Anti-pattern | Why it bites | Do instead |
|--------------|--------------|------------|
| Logic in an adapter | Breaks CLI/Slack parity; duplicated, drifts | Push into the engine; adapter only renders |
| Passing full pipeline state to a worker | Context pollution; small models lose the thread | Pass only the phase input |
| Hard-coding a model in an agent | Can't route by compute; can't swap to cloud | Ask `llm` for a *role* |
| Free-form agent output | Next phase can't consume it reliably | Return a typed artifact |
| Re-deriving orchestration in a prompt each run | Token bloat, inconsistent routing | Load a Skill template |
| Co-loading worker + embedding models | VRAM thrash, stalls | Respect the concurrency guard & quiet hours |
| Auto-applying skill self-edits | A bad reflection silently corrupts every build | Land edits as a reviewable diff |

---

## Related
- [personal-assistant.plans.md](personal-assistant.plans.md) — architecture & features
- [personal-assistant.implementation.md](personal-assistant.implementation.md) — roadmap
- [impl/01-cli-and-core-engine.md](impl/01-cli-and-core-engine.md) — contracts
- [impl/05-meta-agent-and-skills.md](impl/05-meta-agent-and-skills.md) — orchestration
