---
title: "Implementation: Meta-Agent & Skills"
created: 2026-06-20
updated: 2026-06-20
version: 1.0.0
status: Draft
tags: [implementation, meta-agent, langgraph, skills, orchestration]
related:
  - ../personal-assistant.plans.md
  - 01-cli-and-core-engine.md
reference:
  - https://github.com/langchain-ai/langgraph
---

> Whenever this documentation file changes, update the `updated` field and append a new entry to `changelog` describing the revision.

# Implementation: Meta-Agent & Skills (Loop 2)

The Meta-Agent Governor orchestrates the SDLC pipeline. It does **not** write code
or scrape the web — it loads a **Skill** (deterministic template), routes work to
the three Worker Agents via **tools**, enforces phase gates, and recovers from
failures. It runs as a **LangGraph** state machine (D3) on a small local model.

> The strategy is **Skills + Tools hybrid**: the Skill fixes *what order* things
> happen (deterministic routing for our fixed Research→Architect→Developer chain);
> the tools are *how* each step executes (flexible). See the rationale in the main
> plan's "Meta-Agent Strategy" section.

---

## 1. The LangGraph State Machine

```
                ┌───────────────────────────────────────────┐
                │                meta (router)               │
                │  loads Skill, reads Memory, decides next   │
                └───┬───────────┬───────────────┬────────────┘
                    ▼           ▼               ▼
              ┌──────────┐ ┌──────────┐  ┌──────────────┐
              │ research │ │ architect│  │  developer   │
              └────┬─────┘ └────┬─────┘  └──────┬───────┘
                   │            │               │
                   ▼            ▼               ▼ (lint/test?)
              ┌─────────┐  ┌─────────┐    fail ─┘ loop back
              │  gate?  │  │  gate?  │    pass ─► finish
              └─────────┘  └─────────┘
```

```python
# pa/agents/meta/graph.py
from langgraph.graph import StateGraph, END

class BuildState(TypedDict):
    job_id: str
    idea: str
    prefs: dict
    research_report: str | None
    blueprint: str | None
    repo_path: str | None
    error: str | None
    needs_approval: bool

def build_graph(tools, publish) -> "CompiledGraph":
    g = StateGraph(BuildState)
    g.add_node("meta",      meta_router(tools, publish))
    g.add_node("research",  research_node(tools, publish))
    g.add_node("architect", architect_node(tools, publish))
    g.add_node("developer", developer_node(tools, publish))

    g.set_entry_point("meta")
    g.add_conditional_edges("meta", route_next, {
        "research": "research", "architect": "architect",
        "developer": "developer", "done": END,
    })
    # after each worker, return to meta (which enforces gates + decides next)
    g.add_edge("research", "meta")
    g.add_edge("architect", "meta")
    # developer self-loops on lint/test failure, else back to meta
    g.add_conditional_edges("developer", dev_check, {
        "retry": "developer", "ok": "meta",
    })
    return g.compile(checkpointer=sqlite_checkpointer())   # enables replay/time-travel
```

Why LangGraph and not a hand-rolled loop or CrewAI: we need conditional edges
(re-route on failure), a checkpointer (replay a bad run without re-running it), and
human-in-the-loop interrupts (the gates). LangGraph gives all three; a role-based
crew framework does not.

### Phase gates (no context pollution)
The `meta` router is the only node that sees the whole `BuildState`. Each worker
node receives **only** its phase input (research gets the idea + KB hits; architect
gets the report; developer gets the blueprint). This is enforced by what each node
function reads from state — never pass the full state into a worker prompt.

### Failure recovery
- Worker raises / returns malformed output → `meta` re-dispatches that worker with
  an error-correction addendum (bounded retries).
- Developer output fails lint/test → `developer` self-loop edge with the error log.
- Retries exhausted → emit `Result(ok=False)`; the user sees it via either interface.

---

## 2. Human-in-the-Loop Gates

LangGraph's interrupt mechanism parks the graph; the engine publishes
`ApprovalNeeded` and waits for an `Approve` command (Slack button or `pa approve`)
— see [01-cli-and-core-engine.md](01-cli-and-core-engine.md) §3. Gate placement is
a preference (`prefs.gate_policy`): e.g. gate after research (review feasibility
before building) and before the GitHub push. `build --yes` / `auto_approve` skips
gates for trusted, low-risk ideas.

---

## 3. Tools (the execution primitives)

The graph nodes call tools; tools are the only things that touch storage, workers,
or the outside world. Keep them small and typed.

```python
# pa/agents/meta/tools.py
async def query_knowledge_base(query: str, k: int = 8) -> str:
    """Hybrid retrieval + rerank; returns cited markdown context."""

async def dispatch_research_worker(idea: str, kb_context: str) -> str:
    """Run the Research Worker; returns a Research & Feasibility Report."""

async def dispatch_architect_worker(report: str, prefs: dict) -> str:
    """Run the Architect Worker; returns structure + schema + API contracts."""

async def dispatch_developer_worker(blueprint: str, project: str) -> dict:
    """Run the Developer Worker; writes files, returns {repo_path, lint_ok, test_ok}."""

async def publish_progress(job_id: str, phase: str, message: str) -> None:
    """Emit a Progress event to the shared stream (CLI + Slack render it)."""
```

Each `dispatch_*` runs its worker on the **large local coding model** via
`llm/ollama.py`, loading it on demand under the concurrency guard so it never
co-loads with the digest's embedding model.

---

## 4. The Worker Agents

Each worker is a focused prompt + the large model + a narrow toolset. They share
nothing but their typed input/output.

| Worker | Reads | Produces | Tools |
|--------|-------|----------|-------|
| **Research** | idea + KB context | Markdown feasibility report (existing solutions, constraints, stack rec, pitfalls) — cited | `query_knowledge_base`, web fetch (fallback only) |
| **Architect** | research report + prefs | Folder structure, DB schema, API contracts; validated against complexity budget | none (pure reasoning) |
| **Developer** | architecture blueprint | Boilerplate, test stubs, deploy script → `~/projects/<name>/`; runs lint/test | filesystem write, shell (lint/test), optional `git`/`gh` |

The Research Worker queries the **Knowledge Base first** and only falls back to the
web if local knowledge is thin — the Loop 1 → Loop 2 bridge in action.

---

## 5. Skills: deterministic orchestration templates

Skills are version-controlled Markdown in `~/assistant/skills/` (seed copies in the
repo's `skills/`). A Skill is loaded **once** into the meta router's context as the
template it follows — not re-derived per request. This buys consistent routing,
explicit failure handling, and auditability.

### Skill file format
```markdown
# Skill: sdlc-orchestration

## Trigger
A `build` command for a software project/tool idea.

## Steps
1. Research Dispatch
   - query_knowledge_base(idea keywords)
   - dispatch_research_worker(idea, kb_context)
   - GATE (if prefs.gate_policy includes "post_research")
2. Architecture Dispatch
   - dispatch_architect_worker(report, prefs)
   - validate against complexity budget
3. Code Dispatch
   - dispatch_developer_worker(blueprint, project_name)
   - write to ~/projects/<project>/
   - GATE before GitHub push (if enabled)

## Success Criteria
- Report contains 3+ existing solutions, with citations
- Blueprint includes explicit error handling
- Developer output passes lint + tests

## Failure Handling
- Missing report → re-query KB, re-dispatch research
- Architecture gaps → re-route to architect with the gap list
- Lint/test fail → re-route to developer with the error log (bounded retries)
```

### Loader
```python
# pa/skills/loader.py
def load_skills() -> dict[str, str]:
    return {p.stem: p.read_text() for p in Path("~/assistant/skills").expanduser().glob("*.md")}
```

The meta router selects a skill by simple intent match (one fixed skill today;
embeddings-based match later if the library grows) and injects it into the system
prompt as the orchestration blueprint.

---

## 6. Skill Self-Improvement (Phase 3, human-reviewed)

After a run, an optional reflection step writes a compact `run_trace` (what worked,
what failed, what was re-routed) to Persistent Memory. Periodically the system can
*propose* a skill edit from accumulated traces — but proposed edits land as a Git
diff for the user to review and merge, never auto-applied. This closes the learning
loop without letting a flawed reflection silently corrupt every future build.

---

## 7. Why not the alternatives (recap)

| Option | Why not here |
|--------|--------------|
| Pure system-prompt routing | Re-derives orchestration every call → token bloat, inconsistent routing, skipped steps. |
| Pure tool-calling, no skill | Flexible but non-deterministic ordering — wrong for a fixed SDLC chain; harder to audit. |
| CrewAI roles | Weaker conditional re-routing, checkpointing, and HITL interrupts than LangGraph. |

The hybrid (Skill template + LangGraph + tools) is deterministic where we want
determinism and flexible where we want flexibility.

---

## 8. Testing

- **Graph routing:** stub workers; assert the node visit order and that a forced
  lint failure triggers the developer self-loop, then recovers.
- **Context isolation:** assert each worker node receives only its phase input
  (no full-state leakage).
- **Gate:** assert the graph parks on `ApprovalNeeded` and resumes on `Approve`.
- **Skill adherence:** run with a recorded skill; assert the tool-call sequence
  matches the skill's Steps.

---

## Related
- [01-cli-and-core-engine.md](01-cli-and-core-engine.md) — engine, gates, events
- [03-vector-db-and-storage.md](03-vector-db-and-storage.md) — retrieval the tools use
- [agent.architecture-guide.md](../agent.architecture-guide.md) — adding/extending agents
- [../personal-assistant.implementation.md](../personal-assistant.implementation.md)
