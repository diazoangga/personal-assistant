---
title: Agent Architecture & Development Guide
created: 2026-06-20
updated: 2026-06-21
version: 3.0.0
status: Draft
tags: [architecture, agents, skills, tools, guide, contributing]
changelog:
  - version: 1.0.0
    date: 2026-06-20
    changes: "Initial guide for the SDLC project-builder paradigm"
  - version: 2.0.0
    date: 2026-06-21
    changes: >-
      Rewritten for the cognitive-engine paradigm (plans.md v3.0.0). Centered on
      the Agent/Skill/Tool separation (D4) with the decide-vs-compute litmus test,
      the three cognitive agents, the Skill registry, and updated recipes
      (add a skill, a connector, an agent — only when it truly decides).
  - version: 3.0.0
    date: 2026-06-21
    changes: >-
      Updated for plans.md v4.0.0 (five agents). Re-evaluated Research and
      Brainstorming against the decide-vs-compute litmus test and promoted both
      — Research Agent decides research depth/novelty/citation-chasing per
      topic; Brainstorming Agent decides KB-vs-web-vs-handoff per turn. Added a
      recipe for Meta Agent self-modification proposals under the human-review
      gate (D6).
related:
  - personal-assistant.plans.md
  - personal-assistant.implementation.md
---

> Whenever this documentation file changes, update the `updated` field and append a new entry to `changelog` describing the revision.

# Agent Architecture & Development Guide

This is the guide for *working on* the assistant: how the layers fit, the rule that
keeps Agents, Skills, and Tools from collapsing into each other, and recipes for the
common extensions. Read the [plan](personal-assistant.plans.md) and
[roadmap](personal-assistant.implementation.md) first for the *what*; this is the
*how to change it*.

---

## 1. The Layer Model (and the one rule)

```
Interface Adapters  (CLI, Slack)            ← presentation only
        │ Command ↓        ↑ Event
Core Engine          (bus, jobs, queue, loops)  ← orchestration glue
        │
Agents               (Meta, Interest, Research, Opportunity, Brainstorming)  ← decide (Why)
        │
Skills               (classification, retrieval, ranking, graph construction, …)  ← compute (How)
        │
Tools / Infra        (Ollama, vector, memory, graph store, connectors, web search)  ← execute (With What)
```

**The one rule:** dependencies point *downward only*. Adapters may import the Core
Engine; the Core Engine never imports an adapter. Agents use skills; skills use
tools; **tools and skills never import agents.** Need an upward call? Invert it with
an event or an injected callback (`publish`) — never an import.

This is what makes CLI/Slack parity (D2) and the cloud-model escape hatch (D1) cheap.

---

## 2. The Core Distinction You Must Internalize (D4)

```
Agent = Why      Skill = How      Tool = With What
```

Before you build anything, classify it with the **decide-vs-compute** litmus test:

| If it… | it's a… | Examples |
|--------|---------|----------|
| executes one external action, no reasoning | **Tool** | GitHub API, web search call, vector upsert, SQLite write, Ollama call |
| transforms input → output, no state, doesn't choose what's next | **Skill** | Topic Extraction, Gap Analysis, Ranking, Summarization, Citation Graph Construction |
| monitors state over time and **chooses among actions** | **Agent** | Meta, Interest, Research, Opportunity, Brainstorming |

> **The trap this prevents:** an earlier draft had eight "agents" — including a
> *Memory Agent*, *Gap Analysis Agent*, *Serendipity Agent*. None of them decide.
> Memory is a **tool** + a retrieval **skill**; gap analysis and serendipity are
> **skills** of the Opportunity Agent. Those stay merged.
>
> **Research and Brainstorming are different — they were re-evaluated, not
> reinstated by default.** An early-draft *"Research Radar Agent"* was a blind
> scheduled pull with no branch point, so it was correctly demoted to a pipeline.
> The current **Research Agent** is not that: it is *triggered* by an Interest
> Agent classification, then **decides** how deep to chase citations, what's novel
> enough to add to the graph, and when to stop — real choices, not a fixed
> transform. Likewise the **Brainstorming Agent decides**, per turn, whether to
> answer from the KB, fall back to web search, or hand off to the Opportunity or
> Research Agent. Both pass the litmus test as scoped. If either one ever
> degenerates into "always do step 1, 2, 3 in order," that's the signal to demote
> it back to a skill/pipeline.

**Before adding an agent, prove it decides.** If you can't name a branch point where
it acts differently based on context, it's a skill — add it to the registry instead.

---

## 3. The Five Agents (and what each owns)

| Agent | Decides | Owns | Model role |
|-------|---------|------|------------|
| **Meta** | which loop/agent runs, how to classify the user's current activity, whether a recommendation was good, **what skill/prompt/tool change to propose (D6)** | orchestration, activity classification, feedback loop, self-improvement proposals | `meta` (small/fast) |
| **Interest** | what counts as an interest, how strength/decay evolve, what's emerging vs abandoned, when to trigger Research | the interest model + user profile | `meta`/`reasoning` |
| **Research** | how deep to research a triggered topic, which sources to use, what's novel enough for the graph, when to stop chasing citations | citation graph, knowledge graph, KB freshness for a topic | `reasoning` |
| **Opportunity** | what to surface, how to combine research + interest into a proposal scoped to a stated problem, how to rank | idea/recommendation generation | `reasoning` (heavier) |
| **Brainstorming** | KB vs web search vs handoff to Opportunity/Research, per turn | the interactive session; the only agent holding a multi-turn conversation | `reasoning` |

Each is a **full agent**, not a mode of another — see §2's note on why Research and
Brainstorming earned that status this time.
See [impl/05-meta-agent-and-skills.md](impl/05-meta-agent-and-skills.md) (Meta,
Interest, Opportunity), [impl/06-research-agent.md](impl/06-research-agent.md)
(Research), and [personal-assistant.brainstorm-feature.md](personal-assistant.brainstorm-feature.md)
(Brainstorming).

### Meta Agent's authority is bounded by D6

Meta may **propose** a change to a skill, a prompt, or a tool wiring after a
performance review. It may **never apply one unreviewed.** This is not a
permissions nicety — an unsupervised agent rewriting its own prompts or adding
tools is a different risk class than one that merely orchestrates. See Recipe
6.6 below for the concrete workflow.

---

## 4. The Skill Registry is the reuse contract

All skills live in `src/skills/` and are listed canonically in
[plans.md → Skill Registry](personal-assistant.plans.md#the-skill-registry-canonical--d4).
Rules:

1. **One name per capability.** Don't introduce "Relevance Ranking" when
   "Recommendation Ranking" exists. Reuse or rename — never fork.
2. **Skills are pure-ish transforms.** `def run(input, *, llm, store) -> output`.
   They may call tools (LLM, vector) but hold **no goal and no cross-call state**.
3. **Skills are shared.** Topic Extraction is used by Interest, Ingestion, and
   Opportunity — written once.
4. **Skills are the easiest things to test** (deterministic I/O). Cover them well;
   they're where correctness compounds.

---

## 5. Model Routing & Compute Discipline

`llm/openrouter.py` is the single place models are selected and API calls are made.

```python
ROLE_MODELS = {
    "meta": "google/gemma-3b-european-union:free",
    "reasoning": "google/gemma-3b-european-union:free",
    "embedding": "nomic-embed-text"  # local embedding still needed for KB
}

class OpenRouterRuntime:
    async def complete(self, role: str, prompt: str, **kw) -> str: ...
    # embedding still local via Ollama or sentence-transformers
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    # rate limit guard: free tier has request limits
```

- **Never** name a model inside an agent or skill — ask for a *role*.
- The **rate limit guard** prevents exceeding OpenRouter free tier limits. Loops are scheduled to avoid burst requests.
- **Embedding stays local (D1):** embeddings for the KB still run locally (Ollama or sentence-transformers) — only completions use OpenRouter.

---

## 6. Recipes

### 6.1 Add a new command (keep CLI/Slack parity)
1. Add a `Command` subtype in `core/commands.py`.
2. Add a handler + route entry in `core/engine.py` (emit `Progress`/`Result`/`Message`).
3. Bind it in **both** `adapters/cli/app.py` and `adapters/slack/app.py`.
4. Update the parity table in [impl/01](impl/01-cli-and-core-engine.md) §5 and the
   parity test. **A command with only one binding fails CI.**

### 6.2 Add a Skill (the common case — do this before reaching for an agent)
1. Add `src/skills/<name>.py` exposing a typed `run(...)`.
2. Register it in the [Skill registry](personal-assistant.plans.md#the-skill-registry-canonical--d4)
   with its one canonical name and its consumers.
3. Call it from the agent(s) that need it. Reuse across agents — don't copy.
4. Unit-test it directly (pure transform → trivial to test).

### 6.3 Add an Agent (rare — only if it genuinely decides)
1. **First prove it decides** (§2). If not, it's a skill — stop, do 6.2. Name the
   actual branch point ("decides X vs Y based on Z") — if you can't, it's a skill.
2. Add `src/agents/<name>.py` (or a LangGraph subgraph) with a goal, state, and a
   routing decision.
3. Give it the smallest set of skills/tools that does the job; default to a *role*.
4. Decide its **trigger**: a loop tick, another agent's output (e.g. Research is
   triggered by an Interest classification), or a user command. Wire it into the
   Meta Agent's orchestration accordingly.
5. Add it to the agent table in §3 above and to the relevant impl doc
   ([impl/05](impl/05-meta-agent-and-skills.md) or its own impl doc if complex
   enough to warrant one, e.g. [impl/06](impl/06-research-agent.md)).

### 6.6 Meta Agent proposes a self-modification (D6 — always human-reviewed)
1. Meta's performance review (per-agent acceptance/correction rates, run traces)
   identifies a weak point — e.g. "Opportunity Agent's ranking ignores recency."
2. Meta drafts a **proposal**, not a change: which skill/prompt/tool, the diff, and
   the evidence (which traces/metrics motivated it).
3. The proposal is written to a reviewable location (a Git diff / PR, or a row in a
   `proposals` table surfaced via `pa review` / a Slack approval message) — **never
   applied directly to the running skill, prompt, or tool wiring.**
4. You approve, edit, or reject. Only an approved proposal is merged.
5. Record the outcome (approved/rejected + your edits, if any) — it's itself a
   training signal for whether Meta's proposals are getting better.

> If you're ever tempted to add an "auto-apply if confidence > X" path: don't. A
> bad reflection silently corrupting a prompt or adding the wrong tool is exactly
> the failure D6 exists to prevent, and confidence scores from the same system
> being reviewed aren't a trustworthy gate.

### 6.4 Add a signal connector (sensing)
1. Add `src/ingest/connectors/<name>.py` implementing `Connector.fetch -> list[RawSignal]`.
2. Register it in `config/settings.toml [connectors] enabled`. No pipeline changes —
   dedupe/score/chunk/embed are connector-agnostic.
3. **Privacy check:** personal connectors (browser/Slack/calendar) are opt-in and
   must respect the retention/aging policy. Add a record/replay fixture test.

### 6.5 Add or edit an orchestration Skill (Markdown)
1. Edit/create the template in `~/assistant/skills/` (seed copy in repo `skills/`).
2. Keep the sections: Trigger, Steps, Success Criteria, Failure Handling.
3. Git-tracked — review as diffs. Auto-proposed edits (Phase 3 self-improvement)
   land as a reviewable diff, never auto-merge.

---

## 7. Observability & Debugging

- **`pa status <job>`** — current state, phase, log trail (from Persistent Memory).
- **LangGraph checkpointer** — every reasoning run is checkpointed; replay/time-travel
  to the failing node instead of re-running.
- **Run traces** — `run_traces` hold a compact post-run summary feeding both
  debugging and self-improvement.
- **Provenance** — every recommendation/answer logs the signal/source IDs it used;
  "why this?" is always answerable.

---

## 8. Common Anti-Patterns (don't)

| Anti-pattern | Why it bites | Do instead |
|--------------|--------------|------------|
| Promoting a transform to an "agent" | Agent sprawl, the D4 violation | Add it as a skill |
| Treating memory/vector as an agent | Stores don't reason; muddles the layers | Tool + Memory Retrieval skill |
| Logic in an adapter | Breaks CLI/Slack parity | Push into engine; adapter only renders |
| Forking a skill under a new name | Drift, duplicate maintenance | Reuse/rename the registry entry |
| Hard-coding a model | Can't route by compute; can't swap to cloud | Ask `llm` for a *role* |
| Recommendation without provenance | Can't answer "why this?" — the core promise | Carry source/signal IDs through |
| Co-loading reasoning + embedding models | VRAM thrash | Respect the concurrency guard & loop scheduling |
| Meta auto-applying a skill/prompt/tool change (D6) | A bad performance read silently corrupts system-wide behavior | Land every proposal as a reviewable diff; require explicit approval |
| Research Agent pulling everything on a schedule with no depth/novelty decision | Degenerates back into the old "Research Radar" pipeline — not an agent anymore | Keep the depth/novelty/stop decisions real; trigger from Interest, not a timer |
| Brainstorming Agent always retrieving from both KB and web | No real routing decision left — it's just a fixed pipeline wearing an agent's name | Make the KB-vs-web-vs-handoff choice actually conditional on retrieval quality |

---

## Related
- [personal-assistant.plans.md](personal-assistant.plans.md) — architecture & features
- [personal-assistant.implementation.md](personal-assistant.implementation.md) — roadmap
- [personal-assistant.brainstorm-feature.md](personal-assistant.brainstorm-feature.md) — flagship feature
- [impl/01-cli-and-core-engine.md](impl/01-cli-and-core-engine.md) — contracts
- [impl/05-meta-agent-and-skills.md](impl/05-meta-agent-and-skills.md) — Meta, Interest, Opportunity
- [impl/06-research-agent.md](impl/06-research-agent.md) — Research Agent
