---
title: Personal Assistant — Architecture & Feature Plan
created: 2026-06-18
updated: 2026-06-20
version: 2.0.0
status: Draft
tags:
  - architecture
  - plan
changelog:
  - version: 1.0.0
    date: 2026-06-18
    changes: "Initial plan documentation derived from brainstorming session"
  - version: 2.0.0
    date: 2026-06-20
    changes: >-
      Major revision. Locked three foundational decisions: (1) all-local Ollama
      execution for every agent, (2) CLI and Slack as symmetric adapters over a
      single shared Core Engine, (3) LangGraph as the orchestration runtime.
      Added a full feature catalog informed by 2026 agentic-AI research,
      a layered (hexagonal) architecture, a shared command set with CLI/Slack
      parity, and links to the new per-component implementation docs.
audience: Solo developer building a local Linux-based AI personal assistant
reference:
  - https://github.com/langchain-ai/langgraph
  - https://github.com/joaomdmoura/crewAI
  - https://ollama.com
  - https://docs.slack.dev/ai/
  - https://www.langchain.com/resources/ai-agent-frameworks
---

> Whenever this documentation file changes, update the `updated` field and append a new entry to `changelog` describing the revision.

# Personal Assistant — Architecture & Feature Plan

## Summary

This document defines the architecture and feature set for a **locally-running AI
personal assistant** that turns a noisy "idea backlog" into researched,
scaffolded projects. It addresses three chronic problems for a solo developer:
ideas get lost, deep research gets skipped, and execution balloons past capacity.

The system has **two operational loops** (a background Daily Research loop and an
on-demand SDLC pipeline) sitting on top of **one shared Core Engine**. The user
drives that engine through **two symmetric interfaces** — a local **CLI** and a
**Slack** workspace — that expose the *same* command set. Every agent runs
**locally on Ollama**, so the system is private, offline-capable, and free to run.

---

## Foundational Decisions (v2.0.0)

These three decisions are load-bearing; every implementation doc assumes them.

| # | Decision | Rationale |
|---|----------|-----------|
| **D1** | **All agents run locally on Ollama.** No cloud LLM calls. | Privacy, zero per-token cost, offline operation. The Vector DB compresses research to the few relevant paragraphs so small local models stay effective. |
| **D2** | **CLI and Slack are symmetric adapters over one Core Engine.** They expose the same commands and read the same result stream. | Single source of truth for business logic. Use the CLI at the desk; use Slack from the phone. Neither is "primary." |
| **D3** | **LangGraph is the orchestration runtime.** | Best-in-class for cyclical state machines with retries, human-in-the-loop gates, persistence, and time-travel debugging — exactly what the Meta-Agent needs. |

> **Why local over cloud (the trade-off we accepted):** cloud models still win on
> the hardest ~20% of multi-file coding tasks. We mitigate this with (a) tight
> context budgets via the Vector DB, (b) a capable coding model for workers
> (Qwen3-Coder class), and (c) a "tracer bullet" execution style that keeps each
> generation step small. If a future need justifies it, the worker layer is the
> single seam where a cloud model could be swapped in per-agent (see
> [agent.architecture-guide.md](agent.architecture-guide.md)).

---

## Problem Statement

A three-part bottleneck:

1. **Idea capture friction** — no low-barrier way to record and qualify ideas.
2. **Research overhead** — deep technical research before execution is slow and often skipped.
3. **Execution scope creep** — without strict phase boundaries, projects stall or balloon.

The solution shifts the cognitive load of *filtering, structuring, and initial
research* onto a multi-agent system, leaving the human to handle high-level
decisions and final approval.

---

## System Architecture (Layered / Hexagonal)

The architecture is **ports-and-adapters**: a framework-agnostic Core Engine in the
middle, with interchangeable interface adapters (CLI, Slack) on the outside and
infrastructure adapters (Ollama, storage, schedulers) at the bottom. This is what
makes CLI/Slack parity (D2) cheap to maintain.

```
┌───────────────────────────────────────────────────────────────────┐
│                        INTERFACE ADAPTERS                          │
│   ┌────────────────┐                        ┌──────────────────┐   │
│   │  CLI  (`pa`)   │   ── same command ──   │  Slack (Bolt,    │   │
│   │  Typer / Rich  │        set & events    │  Socket Mode)    │   │
│   └───────┬────────┘                        └────────┬─────────┘   │
└───────────┼──────────────────────────────────────────┼────────────┘
            │            Command objects                │
            ▼            (build/research/ask/…)         ▼
┌───────────────────────────────────────────────────────────────────┐
│                        CORE ENGINE (shared)                        │
│  Command Bus → Job Queue → Event Stream (results/progress)         │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │     Meta-Agent Governor  —  LangGraph state machine          │  │
│  │     loads Skills · routes to workers · enforces phase gates  │  │
│  └───────┬───────────────────────┬───────────────────┬─────────┘  │
│          ▼                       ▼                   ▼             │
│  ┌──────────────┐        ┌──────────────┐    ┌──────────────┐      │
│  │  Research    │        │  Architect   │    │  Developer   │      │
│  │  Worker      │        │  Worker      │    │  Worker      │      │
│  └──────────────┘        └──────────────┘    └──────────────┘      │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │   Daily Research Loop   (scheduler-driven ingestion)         │  │
│  │   scrape → dedupe → chunk → embed → store → digest           │  │
│  └─────────────────────────────────────────────────────────────┘  │
└───────────┬───────────────────────────────────────┬───────────────┘
            ▼                                         ▼
   ┌──────────────────────┐                ┌──────────────────────────┐
   │  Knowledge Base       │               │  Persistent Memory        │
   │  Qdrant / pgvector    │               │  SQLite (+ optional PG)    │
   │  hybrid search+rerank │               │  job state · prefs · tasks │
   └──────────┬───────────┘                └──────────────────────────┘
              ▲
   ┌──────────┴────────────────────────────────────────────────────┐
   │  Ollama Runtime                                                │
   │  meta → 8B (fast routing)   workers → Qwen3-Coder 30B          │
   │  embeddings → nomic-embed / bge-m3                             │
   └────────────────────────────────────────────────────────────────┘
```

**The seam that matters:** the Command Bus + Event Stream. An interface adapter's
only job is to (1) translate user input into a `Command`, and (2) render
`Events` (progress, results, approval requests) back to the user. All logic lives
below that line, so adding or changing an interface never touches agent logic.

---

## Two Loops, One Engine

| | **Loop 1 — Daily Research** | **Loop 2 — SDLC on Demand** |
|---|---|---|
| Trigger | Scheduler (cron / APScheduler) @ 07:00 | `pa build` / `/build` |
| Driver | Daily Research Agent | Meta-Agent Governor |
| Output | Curated digest → `#daily-intelligence` + CLI | Research report → architecture → scaffolded repo |
| Writes to | Knowledge Base (Vector DB) | Local workspace / GitHub repo + Persistent Memory |

> **The bridge:** Loop 1 continuously fills the Knowledge Base. When Loop 2 runs,
> the Meta-Agent queries that accumulated research *first*, before any live web
> request. Yesterday's reading becomes today's feasibility report.

---

## Components

### 1. Core Engine
The framework-agnostic heart. Owns the Command Bus, the async Job Queue, the
Event Stream, the Meta-Agent, the workers, and all storage access. Exposes a
single in-process API (`engine.submit(command) -> job_id`) that both adapters call.
See [impl/01-cli-and-core-engine.md](impl/01-cli-and-core-engine.md).

### 2. Interface Adapters (symmetric — D2)

| Interface | Tech | Role |
|-----------|------|------|
| **CLI** (`pa`) | Typer + Rich | Desk-side control, scripting, config, live progress in terminal. |
| **Slack** | `slack_bolt` (Socket Mode) | Remote/mobile control, daily digest delivery, interactive approval buttons. |

Both build identical `Command` objects and subscribe to the same `Event` stream.
The shared command set is defined in [the Command Set table](#shared-command-set-cli--slack-parity).

### 3. Meta-Agent Governor (LangGraph)
The orchestrating layer. It does **not** write code or scrape the web. It:
- Receives a `build` command, reads state + preferences from Persistent Memory.
- Loads the relevant **Skill** (deterministic orchestration template).
- Routes tasks to workers, passing each only its phase-relevant context.
- Enforces strict phase gates (no context pollution between phases).
- Catches worker failures and re-routes with an error-correction prompt before escalating to the user.

**Model:** small/fast local model (8B class) — routing is high-frequency and cheap.
See [impl/05-meta-agent-and-skills.md](impl/05-meta-agent-and-skills.md).

### 4. Worker Agents (Loop 2)
Instantiated on demand; each receives only its phase input.

| Agent | Phase | Input | Output |
|-------|-------|-------|--------|
| **Research Worker** | 1 | Idea + Vector DB hits | Markdown Research & Feasibility Report |
| **Architect Worker** | 2 | Research report | Folder structure, DB schema, API contracts |
| **Developer Worker** | 3 | Architecture blueprint | Boilerplate, test stubs, deploy scripts → workspace/GitHub |

**Model:** larger local coding model (Qwen3-Coder 30B class), loaded only when a
worker runs to avoid simultaneous VRAM pressure with the digest job.

### 5. Daily Research Agent (Loop 1)
Background ingestion pipeline: pull sources → deduplicate → semantic-chunk →
embed → store with provenance → post categorized digest.
See [impl/04-daily-research-agent.md](impl/04-daily-research-agent.md).

### 6. Storage Layer

| Layer | Tool | Stores | Purpose |
|-------|------|--------|---------|
| **Knowledge Base** | Qdrant or `pgvector` (Docker) | Scraped research, docs, boilerplates | Hybrid semantic+keyword search; protects the LLM context window |
| **Persistent Memory** | SQLite (PG optional later) | Job/phase state, prefs, task lists, chat summaries | Execution continuity across commands and interfaces |

See [impl/03-vector-db-and-storage.md](impl/03-vector-db-and-storage.md).

### 7. Skills Library
Versioned Markdown files in `~/assistant/skills/` (Git-tracked). Each skill is a
deterministic orchestration template the Meta-Agent loads instead of free-form
reasoning. The system can also *write new skills* by reflecting on completed runs.

### 8. LLM Runtime (Ollama)
One local runtime serving all roles via per-role model routing. Concurrency is
managed so the heavy worker model and the digest job don't contend for VRAM.

---

## Shared Command Set (CLI ↔ Slack Parity)

The contract that realizes D2. Every command exists in both interfaces and maps to
the same Core Engine `Command`.

| Intent | CLI | Slack | Effect |
|--------|-----|-------|--------|
| Build a project | `pa build "<idea>"` | `/build <idea>` | Run the SDLC pipeline (Loop 2) |
| Run research now | `pa research now` | `/research` | Trigger an ad-hoc ingestion + digest |
| Show digest | `pa digest [date]` | `/digest` | Render latest/﻿given daily digest |
| Ask the knowledge base | `pa ask "<q>"` | `/ask <q>` | Agentic RAG query with citations |
| Job status | `pa status [job]` | `/status` | Live state of running/recent jobs |
| Approve a gate | `pa approve <job>` | `Approve` button / `/approve` | Pass a human-in-the-loop checkpoint |
| Cancel a job | `pa cancel <job>` | `/cancel <job>` | Abort a running pipeline |
| Preferences | `pa config set <k> <v>` | `/prefs set <k> <v>` | Manage user prefs (stack, language, paths) |
| Tracked topics | `pa topics add/list/rm` | `/topics …` | Manage daily-research interest classes |
| Skills | `pa skills list/edit/new` | `/skills …` | Inspect/manage the skill library |

> Implementation note: both adapters import the same `commands` module. A new
> command is added once in the Core Engine and surfaced in each adapter's thin
> dispatch table — never reimplemented.

---

## Feature Catalog

Grouped by area. Tiers: **MVP** (Phase 0–1), **Core** (Phase 2), **Enhanced**
(Phase 3+). Features marked 🆕 were added in v2.0.0 based on 2026 agentic-AI
research (persistent memory, proactivity, hybrid retrieval, HITL, provenance).

### A. Idea & SDLC Pipeline
| Feature | Tier | Notes |
|---------|------|-------|
| 3-question idea qualifier (hypothesis / value / complexity) | MVP | Gate before any agent runs |
| On-demand SDLC pipeline (Research → Architect → Developer) | MVP→Core | LangGraph phase gates |
| Pre-Flight Brief (landscape, stack rec, unknown-unknowns) | Core | Research Worker output |
| Tracer-bullet phased execution (0/1/2) | Core | Keeps generations small for local models |
| Auto re-route on worker failure (lint/test fail → re-dispatch) | Core | LangGraph conditional edges |
| 🆕 Human-in-the-loop approval gates | Core | Slack buttons / `pa approve` between phases |
| 🆕 GitHub repo creation + initial push | Enhanced | Optional; falls back to local workspace |
| 🆕 Complexity budgeting | Enhanced | Architect validates scope against declared complexity |

### B. Daily Intelligence (Research Loop)
| Feature | Tier | Notes |
|---------|------|-------|
| Scheduled multi-source ingestion (blogs, HN, GitHub Trending, arXiv) | MVP | Pluggable source adapters |
| Categorized digest to `#daily-intelligence` + CLI | MVP | Markdown / Slack Block Kit |
| 🆕 Deduplication + quality scoring on ingest | Core | Avoids accumulating noise |
| 🆕 Semantic chunking | Core | Topic-boundary chunks beat fixed-size |
| User-configurable topic classifications (3–5) | MVP | `pa topics` / `/topics` |
| 🆕 Data aging / pruning policy (e.g. drop > 90 days) | Enhanced | Keeps KB fresh and small |
| 🆕 Proactive alerts (notify when a tracked topic has a major hit) | Enhanced | "Initiates contact" pattern |

### C. Knowledge & Memory
| Feature | Tier | Notes |
|---------|------|-------|
| Vector Knowledge Base | MVP | Qdrant/pgvector |
| 🆕 Hybrid retrieval (vector + BM25/keyword) + rerank | Core | Fastest-growing 2026 RAG pattern; best quality/cost |
| 🆕 Provenance + field-level citations on answers | Core | Every `ask` answer is traceable to a source |
| Persistent cross-session memory (prefs, state, task lists) | MVP | SQLite; table-stakes in 2026 |
| 🆕 Episodic memory (past run traces) | Enhanced | Feeds skill self-improvement |
| 🆕 Agentic RAG for multi-hop questions | Enhanced | Used by `ask` when a single hop is insufficient |

### D. Interface & Interaction
| Feature | Tier | Notes |
|---------|------|-------|
| Symmetric CLI + Slack command set | MVP | D2 |
| Live progress streaming (CLI Rich / Slack message updates) | Core | Shared Event Stream |
| Async job model (ack < 3s, work in background) | MVP | Required by Slack's 3s rule |
| Interactive Slack Block Kit (buttons, modals) | Core | Approvals, digests |
| Preference & topic management commands | MVP | `config` / `topics` |

### E. Reliability, Observability & Ops
| Feature | Tier | Notes |
|---------|------|-------|
| Job queue with status, cancel, retry | Core | One place to see all work |
| 🆕 Run logs + LangGraph time-travel debugging | Core | Replay/inspect any pipeline run |
| 🆕 Local compute metering (VRAM, latency, tokens-equiv) | Enhanced | Tune model routing |
| Model routing per agent role | MVP | Small for meta, large for workers |
| Concurrency guard (no digest job during build hours) | Core | Avoid VRAM contention |
| 🆕 Skill self-improvement (reflect → write new skill) | Enhanced | Closes the learning loop safely, human-reviewed |

---

## The Three-Stage Idea Pipeline (Capture → Research → Execute)

### Stage 1 — Capture & Sift
Raw ideas pass a **3-Question Qualifier** before any agent runs:
1. **Core hypothesis** — "If I build X, it solves Y."
2. **Immediate value** — strategic, financial, or pure learning?
3. **Complexity level** — trivial micro-project vs. enterprise-grade?

### Stage 2 — Automated Research (Pre-Flight Brief)
```
📋 Pre-Flight Brief
├── Landscape & Precedents     → existing libraries, SaaS, OSS repos
├── Tech Stack Recommendation  → fastest tools for MVP; minimal setup
└── Unknown Unknowns Block     → API limits, architectural traps, math/logic blockers
```

### Stage 3 — Incremental Execution (Tracer Bullet)
| Phase | Horizon | Focus | Agent role |
|-------|---------|-------|-----------|
| **0. Tracer Bullet** | 24–48h | End-to-end skeleton proving the core concept | Init scripts, config, minimal boilerplate |
| **1. Core Logic** | 1–2 wk | Primary business/algorithmic logic | Daily atomic checkpoints |
| **2. Polish & Scale** | Ongoing | UI, error handling, optimization | Reviews + edge-case tests |

---

## SDLC Flow (On-Demand)

```
[ pa build "an events scraper" ]   ── or ──   [ /build an events scraper ]
            │
            ▼
   [ Interface Adapter ]  ──► ack < 3s, returns a job_id, streams progress
            │  Command(build, idea, user)
            ▼
   [ Core Engine: Job Queue → Meta-Agent (LangGraph) ]
            │
            ├─► Read Persistent Memory (prefs, current state)
            ├─► Load Skill: sdlc-orchestration
            │
            ├─► 1. Research Worker
            │       query Knowledge Base (hybrid) → Research & Feasibility Report
            │
            ├─► ⏸ HITL gate (optional): user approves report  ── Slack button / pa approve
            │
            ├─► 2. Architect Worker
            │       consume report → file structure + schema + API contracts
            │
            └─► 3. Developer Worker
                    consume blueprint → code + tests + deploy script
                    write to ~/projects/<name>/  (+ optional GitHub push)
            │
            ▼
   [ Event: completion ]
   CLI: rich summary + path     Slack: "✨ ready! 📦 <repo/path>"
```

---

## Local Linux Infrastructure

### Tech Stack
| Component | Tool | Notes |
|-----------|------|-------|
| Orchestration | **LangGraph** | Cyclical state machine, retries, HITL, persistence |
| Local LLM runtime | **Ollama** | Serves all roles; per-role model routing |
| Meta-Agent model | 8B class (e.g. Llama 3.1 8B / Qwen3 8B) | Fast routing |
| Worker model | Qwen3-Coder 30B (or Devstral 24B) | Loaded on demand |
| Embeddings | nomic-embed-text / bge-m3 (local) | For ingestion + retrieval |
| Vector DB | Qdrant or `pgvector` (Docker) | Hybrid search + rerank |
| Persistent memory | SQLite (PostgreSQL optional) | State + sessions |
| CLI | Typer + Rich | `pa` command |
| Slack | `slack_bolt` (Socket Mode) | Slash commands + Block Kit |
| Scheduler | cron or APScheduler | Daily research trigger |
| Lang/runtime | Python 3.11+, `uv`/`venv` | Single package, two entrypoints |

### Compute Considerations
- **Meta-Agent routing:** small 8B model — fast, low VRAM.
- **Workers:** load the large coding model only when a worker runs.
- **Avoid simultaneous load:** don't schedule the digest cron during expected `/build` hours; the concurrency guard enforces this.
- **Context efficiency:** the Vector DB filters gigabytes of research down to the top few paragraphs before waking a model — critical on local hardware.

---

## Why Local-Only + LangGraph (vs. alternatives we considered)

| Alternative | Why not (for this build) |
|-------------|--------------------------|
| **Cloud LLM workers** | Better on the hardest tasks, but breaks the privacy/offline/zero-cost goal (D1). Kept as a per-worker swap-in seam only. |
| **Hermes single-agent loop** | SQLite FTS5 is keyword-only (misses varied terminology); single loop risks context pollution across phases; no bulk dedup/pruning. We adopt its skills idea but keep a dedicated vector DB + LangGraph state machine. |
| **CrewAI** | Great prototype ergonomics, weaker production observability and error recovery than LangGraph — and we need re-routing + HITL gates. |
| **Slack-only frontend (v1.0)** | Replaced by symmetric CLI+Slack (D2) so desk work isn't gated on a network round-trip and the system is scriptable. |

---

## Implementation Phases

### Phase 0 — Tracer Bullet (Week 1)
- [ ] Stand up Core Engine skeleton: Command Bus + in-memory Job Queue + Event Stream
- [ ] CLI adapter (`pa build`, `pa status`) wired to the engine
- [ ] Ollama running with one meta model + one worker model; per-role routing config
- [ ] Local Qdrant/pgvector in Docker
- [ ] Single-agent proof: `build` → Research Worker → result rendered in CLI
- [ ] Validate a Knowledge Base query returns relevant results

### Phase 1 — Daily Research Loop + Slack (Week 2)
- [ ] Slack adapter (Socket Mode): `/build`, `/status` reach the *same* engine
- [ ] Define interest classifications (3–5 topics) + `topics` command
- [ ] Daily Research Agent: scrape → dedupe → semantic-chunk → embed → store
- [ ] Post `#daily-intelligence` digest (Block Kit) + `pa digest`
- [ ] Validate KB is populated with meaningful, deduplicated entries

### Phase 2 — Full SDLC Pipeline (Weeks 3–4)
- [ ] Meta-Agent Governor as a LangGraph state machine with phase gates
- [ ] Architect Worker (schema + file structure + API contracts)
- [ ] Developer Worker (code + tests → local filesystem, optional GitHub push)
- [ ] Loop-back logic: Developer output fails lint/test → re-route to Developer node
- [ ] HITL approval gate between phases (Slack button + `pa approve`)
- [ ] Hybrid retrieval + rerank for `ask`/Research queries

### Phase 3 — Polish & Hardening (Ongoing)
- [ ] Data aging/pruning policy on the Vector DB
- [ ] Quality scoring + stronger dedup on ingestion
- [ ] Proactive alerts on major tracked-topic hits
- [ ] Episodic memory + skill self-improvement (human-reviewed)
- [ ] Compute metering + per-role model tuning

---

## Reference System Prompts

### Meta-Agent Governor
```
You are an Elite Technical Chief of Staff and Meta-Agent Governor.
Your job is to take raw project ideas and orchestrate a structured multi-agent
SDLC pipeline. You never write code or scrape the web yourself.

When you receive a build command, you will:
1. Summarize the core hypothesis in 2 sentences.
2. Load the relevant orchestration Skill and follow its steps.
3. Determine which worker agents are required for this specific request.
4. Pass only the minimal, relevant context to each agent — never the full raw data.
5. Enforce strict phase gates: no agent proceeds without the previous agent's
   structured output (and the user's approval where a HITL gate is configured).
6. If any agent fails, re-route to that agent with an error-correction prompt
   before escalating to the user.

You operate on: [user preferences from Persistent Memory].
You have access to: [Knowledge Base of daily research].
```

### Research Worker
```
You are an expert Technical Research Agent.
Evaluate the technical feasibility of a feature specification using the local
Knowledge Base first, then the web only if needed. Provide:

1. EXISTING SOLUTIONS: 2–3 OSS libraries or SaaS tools that already solve this.
2. BREAKING CONSTRAINTS: API rate limits, auth hurdles, pricing blockers.
3. TECH STACK RECOMMENDATION: most efficient modern stack for execution speed
   and low maintenance.
4. POTENTIAL PITFALLS: common architectural traps for this feature type.

Output a clean Markdown "Research & Feasibility Report". Cite sources.
Return only actionable engineering data — no generic summaries.
```

---

## Meta-Agent Strategy: Skills + Tools Hybrid

The orchestration approach is **Skills-based templates driving Tool calls**:

- **Skills** (Markdown in `~/assistant/skills/`, Git-tracked) are deterministic
  orchestration blueprints loaded once into context — consistent routing, explicit
  failure handling, easy to audit and edit.
- **Tools** are the execution primitives the Skill invokes
  (`query_knowledge_base`, `dispatch_research_worker`, `dispatch_architect_worker`,
  `dispatch_developer_worker`, `post_result`).

This gives deterministic routing for our fixed Research→Architect→Developer chain
while keeping per-step execution flexible. Full design, including the skill file
format, loader, and the LangGraph node wiring, is in
[impl/05-meta-agent-and-skills.md](impl/05-meta-agent-and-skills.md).

---

## Related Documents

- [personal-assistant.implementation.md](personal-assistant.implementation.md) — consolidated build roadmap, milestones, repo layout
- [impl/01-cli-and-core-engine.md](impl/01-cli-and-core-engine.md) — Core Engine, Command Bus, CLI adapter
- [impl/02-slack-gateway.md](impl/02-slack-gateway.md) — Slack Bolt adapter, async/ack, Block Kit
- [impl/03-vector-db-and-storage.md](impl/03-vector-db-and-storage.md) — Knowledge Base + Persistent Memory
- [impl/04-daily-research-agent.md](impl/04-daily-research-agent.md) — ingestion, dedup, chunking, digest
- [impl/05-meta-agent-and-skills.md](impl/05-meta-agent-and-skills.md) — LangGraph orchestration + skill library
- [agent.architecture-guide.md](agent.architecture-guide.md) — agent development & extension guide
