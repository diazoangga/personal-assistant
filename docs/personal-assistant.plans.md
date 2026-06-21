---
title: Personal Assistant — Architecture & Feature Plan
created: 2026-06-18
updated: 2026-06-21
version: 4.0.0
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
      Major revision. Locked three foundational decisions: all-local Ollama,
      symmetric CLI/Slack over a shared Core Engine, LangGraph orchestration.
      Framed the system as an idea→research→scaffold SDLC project builder.
  - version: 3.0.0
    date: 2026-06-21
    changes: >-
      Paradigm change. Dropped the SDLC builder; introduced the cognitive-engine
      paradigm with the Agent/Skill/Tool separation (D4), the three-loop sensing
      model (D5), and three cognitive agents (Meta, Interest, Opportunity).
  - version: 4.0.0
    date: 2026-06-21
    changes: >-
      Restored a Research Agent and promoted Brainstorming to a full agent —
      five agents total. Research Agent is triggered by Interest Agent
      classifications, researches papers/GitHub/Medium/news, and builds a
      citation graph + knowledge graph (this passes the decide-vs-compute test:
      it chooses research depth and novelty, unlike the earlier "Research Radar"
      pipeline it replaces). Brainstorming Agent owns web search as a tool and
      can invoke the Research Agent mid-session. Added D6: Meta Agent may modify
      skills/prompts/tools based on performance review, but every such change is
      human-reviewed before taking effect — never auto-applied.
audience: Solo developer building an AI personal assistant with OpenRouter
reference:
  - https://github.com/langchain-ai/langgraph
  - https://openrouter.ai
  - https://docs.slack.dev/ai/
  - https://qdrant.tech
---

> Whenever this documentation file changes, update the `updated` field and append a new entry to `changelog` describing the revision.

# Personal Assistant — Architecture & Feature Plan

## Vision

This is **not a chatbot and not a coding assistant.** It is a **continuous
cognitive engine.**

Its purpose is to continuously **observe, understand, and model** the user's
activities, interests, knowledge, projects, and working patterns — and from that
model **proactively generate insights, opportunities, and recommendations.**

The system evolves alongside the user and gets more useful over time through
accumulated knowledge, memory, feedback, and self-improvement. The goal is not to
*answer questions on demand*; it is to **continuously discover opportunities,
understand the user, and improve itself.**

---

## Foundational Decisions

These are load-bearing; every implementation doc assumes them.

| # | Decision | Rationale |
|---|----------|-----------|
| **D1** | **All agents use OpenRouter with Gemma4-31B (free tier).** Cloud LLM calls via OpenRouter API. | Gemma4-31B free tier provides strong reasoning at zero cost while avoiding local VRAM constraints. Privacy handled through selective signal filtering before API calls. |
| **D2** | **CLI and Slack are symmetric adapters over one Core Engine.** Same commands, same result stream. | Single source of truth for logic. Neither interface is "primary." |
| **D3** | **LangGraph is the orchestration runtime.** | Cyclical state machines, checkpointing, human-in-the-loop interrupts, conditional routing — what the loops and multi-agent handoffs need. |
| **D4** | **Strict Agent / Skill / Tool separation.** | Prevents the system from degenerating into a pile of over-specialized agents. See [The Core Distinction](#the-core-distinction-agents-vs-skills-vs-tools). |
| **D5** | **The system is signal-driven and continuous, not one-shot.** Sensing → Understanding → Research → Insight. | A cognitive engine runs whether or not the user asks. See [Loops & Triggers](#loops--triggers). |
| **D6** | **Meta Agent may propose changes to skills, prompts, or tools — but every change is human-reviewed before it takes effect.** | Self-improvement is valuable; an unsupervised agent rewriting its own prompts/tools is a real safety risk. The gate is the same principle already applied to skill self-improvement, now stated as a system-wide rule. |

---

## The Core Distinction: Agents vs Skills vs Tools (D4)

```
Agent = Why      (decides — chooses among actions over time, holds a goal & state)
Skill = How      (computes — a reusable transform; no goal, no decisions)
Tool  = With What (executes — an external action; no reasoning)
```

**Litmus test — "does it decide, or does it compute?"**

- **Tool** — executes one external action, no reasoning. *(GitHub API call, web search call, vector upsert.)*
- **Skill** — a pure transform: input → output, no persistent state, doesn't choose what happens next. *(Text in → topics out.)*
- **Agent** — monitors state over time and **chooses among actions**. If you cannot name a branch point where it acts differently based on context, it is **not** an agent.

> **Why Research and Brainstorming qualify as agents (and a prior "Research Radar"
> didn't):** a fixed scheduled pull is a pipeline. The **Research Agent** decides
> *how deep* to go per topic, *what's novel* enough for the graph, and *when to stop*
> chasing citations — genuine iterative decisions. The **Brainstorming Agent**
> decides KB-vs-web-vs-handoff-to-Research per turn. Both have a real branch point;
> that's what earns the agent label.

---

## High-Level Architecture

```
                                  User
                                   │   signals in ▲    insights out ▼
                                   ▼
                           Meta Agent (Brain)
       orchestrate · classify activity · feedback loop · propose self-improvements (D6, gated)
                                   │
        ┌──────────────┬───────────┴───────────┬──────────────┐
        ▼              ▼                       ▼              ▼
  Interest Agent   Research Agent       Opportunity Agent  Brainstorming Agent
  models who       triggered by         recommends what    on-demand: ask
  you are          Interest; builds     to do next, from    anything (KB +
  (topics,         citation graph +    interest + research  web search); can
  strength,        knowledge graph                          invoke Research
  decay)                                                    mid-session
        │              │                       │              │
        └──────────────┴── shared Skills ──────┴──────────────┘
        Classification · Topic Extraction · Entity/Relationship Extraction ·
        Citation Graph Construction · Knowledge Graph Construction · Clustering ·
        Trend Detection · Summarization · Memory Retrieval · Hybrid Retrieval ·
        Query Reformulation · Recommendation Ranking · Gap Analysis ·
        Concept Expansion · Concept Synthesis
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        ▼                          ▼                          ▼
  Activity Sensing            Knowledge Base /            External Tools
  pipeline (NOT an agent;     Graph store + Memory         Ollama · Qdrant ·
  browser/calendar/Slack/     store (NOT agents;           SQLite · GitHub API ·
  GitHub-activity feed        tools)                       Web Search · arXiv ·
  Interest Agent)                                          GitHub Trending · Medium/news
```

Meta orchestrates. Agents invoke Skills. Skills may invoke Tools.

```
Interest Agent  →  classify "LLM agents" as emerging  →  triggers
Research Agent  →  Topic Extraction + Citation Graph Construction  →  arXiv tool, GitHub API tool
   (why)               (how)                                            (with what)
```

---

## Loops & Triggers (D5)

Four stages; the first is scheduled, the rest are reactive/on-demand.

| | **Sensing** | **Understanding** | **Research** | **Insight** |
|---|---|---|---|---|
| Trigger | Scheduler (hourly) | New activity signal | **Interest Agent classification** (new/strengthened interest) | Scheduled digest **+** on-demand (`brainstorm`/`ask`) |
| Driver | Activity Sensing pipeline (not an agent) | Interest Agent | **Research Agent** | Opportunity Agent + Meta Agent |
| Does | pull activity signals → dedupe → store; tag | update interest graph, strength/decay, emerging/abandoned; classify activity | fetch papers/GitHub/Medium/news for the topic; decide depth; build citation + knowledge graph | rank opportunities, synthesize ideas, answer questions, deliver |
| Writes | raw signal log | Interest graph, activity context | Knowledge Base, citation graph, knowledge graph | Opportunities store, digests, memory |

> **The bridge:** Sensing feeds Understanding. Understanding's classifications
> *trigger* Research — research is no longer a blind scheduled pull; it is targeted
> at what the Interest Agent has just decided matters. Insight reasons over the
> Research Agent's graphs plus the Interest model — *"given everything I now know
> about you and the world, here is what's worth your attention."*

---

## Components

### 1. Core Engine
The interface-agnostic heart. Owns the Command Bus, async Job Queue, Event Stream,
the agents, the loops, and all storage access.
See [impl/01-cli-and-core-engine.md](impl/01-cli-and-core-engine.md).

### 2. Interface Adapters (symmetric — D2)
CLI (`pa`, Typer+Rich) and Slack (`slack_bolt`, Socket Mode) — same `Command`s, same
`Event` stream.

### 3. Meta Agent (the Brain)
Orchestrates the other four agents and the loops, **classifies current activity**
(work / research / personal project / learning / exploration), runs the **feedback
loop**, and — per **D6** — may **propose** changes to skills, prompts, or tool
wiring after a performance review. Proposals land as a reviewable diff; nothing
self-modifies without your approval. See [impl/05-meta-agent-and-skills.md](impl/05-meta-agent-and-skills.md).

### 4. Interest Agent
Models *who the user is*: topics of interest, hierarchical taxonomy, **interest
strength and decay**, **emerging**/**abandoned** detection, the long-term user
profile. Its classifications are the trigger for the Research Agent.
See [impl/05-meta-agent-and-skills.md](impl/05-meta-agent-and-skills.md).

### 5. Research Agent
Triggered by an Interest Agent classification (new or strengthened interest). Fetches
papers (arXiv), GitHub (trending/relevant repos), Medium, and news for that topic;
decides how deep to go and what's novel; builds a **citation graph** (paper → paper)
and a **knowledge graph** (concept/entity relationships). Feeds both the Knowledge
Base and the Opportunity Agent. Can also be invoked on demand by the Brainstorming
Agent or via `pa research <topic>`.
See [impl/06-research-agent.md](impl/06-research-agent.md).

### 6. Opportunity Agent
The **primary value producer.** Synthesizes ideas, recommendations, and learning
paths from the Research Agent's graphs + the Interest model + memory, scoped to your
**current problem or issue**. Absorbs Gap Analysis, Concept Expansion (serendipity),
and Ranking as *skills*. Every output traces to specific evidence.
See [impl/05-meta-agent-and-skills.md](impl/05-meta-agent-and-skills.md).

### 7. Brainstorming Agent
Interactive, multi-turn. Ask anything — answers ground in the Knowledge Base first,
**web search** when KB coverage is thin, always cited. Can hand off to the
Opportunity Agent for ideation, or invoke the Research Agent mid-session ("go deep on
this, then propose"). A full agent (owns the KB-vs-web-vs-handoff decision per turn),
not a Meta Agent mode. See [personal-assistant.brainstorm-feature.md](personal-assistant.brainstorm-feature.md).

### 8. Activity Sensing Pipeline (NOT an agent)
A scheduled, skill-driven pipeline that pulls **activity** signals only (browser,
calendar, Slack, GitHub commits/repos) → dedupes → tags → emits signal events for the
Interest Agent. No goal, no choices — a pipeline.
See [impl/04-daily-research-agent.md](impl/04-daily-research-agent.md).

### 9. Storage Layer

| Layer | Tool | Stores | Purpose |
|-------|------|--------|---------|
| **Knowledge Base** | Qdrant or `pgvector` | Research Agent's fetched content, chunked + embedded | Hybrid semantic+keyword retrieval |
| **Graph Store** | SQLite (node/edge tables) | Citation graph, knowledge graph | Built by Research Agent; read by Opportunity + Brainstorming |
| **Persistent Memory** | SQLite | User profile, interest graph, opportunities, signal log, feedback, jobs | The user model + the feedback record |

Memory and the graph store are **Tools** (plus retrieval **Skills**) — not agents.
See [impl/03-vector-db-and-storage.md](impl/03-vector-db-and-storage.md).

### 10. Skills Library & 11. LLM Runtime (Ollama)
See the registries below. One local runtime, per-role model routing, concurrency
guard.

---

## The Skill Registry (canonical — D4)

| Skill | Computes | Used by |
|-------|----------|---------|
| **Classification** | activity / content / intent → category | Meta, Interest, Brainstorming |
| **Topic Extraction** | text → concepts/topics/tags | Interest, Research, Opportunity |
| **Entity & Relationship Extraction** | text → entities + relations | Research |
| **Citation Graph Construction** | papers → paper→paper citation edges | Research |
| **Knowledge Graph Construction** | text/entities → concept graph | Research |
| **Clustering** | items → grouped topics/taxonomy | Interest |
| **Trend Detection** | signal time series → emerging/abandoned/strength | Interest |
| **Summarization** | text(s) → summary; cited variant for grounded answers | Research, Opportunity, Brainstorming |
| **Memory Retrieval** | query → ranked memories + assembled context | Meta, Opportunity, Brainstorming |
| **Hybrid Retrieval** | query → ranked KB chunks (dense+sparse+rerank) | Brainstorming, Opportunity, Research |
| **Query Reformulation** | hard question → sub-queries (agentic multi-hop) | Brainstorming, Opportunity |
| **Recommendation Ranking** | candidates → scored/prioritized list | Opportunity |
| **Gap Analysis** | profile vs landscape → missing concepts / weak areas | Opportunity |
| **Concept Expansion** | a concept → adjacent/cross-domain concepts (serendipity) | Opportunity |
| **Concept Synthesis** | research + interest → novel idea/proposal | Opportunity |

> If you're tempted to add an **agent**, first check this list. It's usually a skill.

---

## Tools

| Tool | Action |
|------|--------|
| Ollama runtime | LLM completion + embeddings (per-role routing) |
| Vector DB (Qdrant/pgvector) | upsert / hybrid search / prune |
| Memory store (SQLite) | read/write profile, interest graph, opportunities, jobs, prefs, feedback |
| Graph store (SQLite) | read/write citation graph, knowledge graph nodes/edges |
| GitHub API | activity signal (your commits/repos) **and** research signal (trending/relevant repos for a topic) |
| Web Search | live web query — Brainstorming Agent's fallback when KB coverage is thin |
| Slack API | read conversations (activity signal) + post (delivery) |
| Browser-history connector | recent visited pages as activity signal |
| Calendar | events as activity-context signal |
| arXiv / Medium / News sources | research signal — fetched by the Research Agent |
| File system | local documents as signal |

---

## Feature Catalog

Tiers: **MVP** (Phase 0–1), **Core** (Phase 2), **Enhanced** (Phase 3+).

### A. User Understanding
| Feature | Tier | Notes |
|---------|------|-------|
| Interest model (topics, strength, hierarchy) | MVP→Core | Interest Agent |
| Interest evolution (emerging / abandoned / decay) | Core | Trend Detection |
| Activity classification | Core | Meta Agent |
| Long-term user profile | MVP→Core | Persistent Memory |

### B. Research & Knowledge
| Feature | Tier | Notes |
|---------|------|-------|
| Activity-only sensing pipeline | MVP | GitHub activity first; browser/Slack/calendar later, opt-in |
| **Research Agent** triggered by Interest classification | Core | The flagship sensing→research bridge |
| Citation graph (papers) | Core | Research Agent |
| Knowledge graph (concepts/entities) | Core | Research Agent |
| Hybrid retrieval (vector + BM25) + rerank | Core | Used by Brainstorming/Opportunity/Research |
| Data aging / pruning | Enhanced | Drop stale signals; pin referenced ones |

### C. Insight & Opportunity
| Feature | Tier | Notes |
|---------|------|-------|
| **Brainstorm** (interactive ask + ideate, KB + web search) | Core | [personal-assistant.brainstorm-feature.md](personal-assistant.brainstorm-feature.md) |
| Brainstorm → Research Agent handoff ("research this, then propose") | Core | Resolves the brainstorm doc's open question |
| `ask` — one-shot cited Q&A | MVP | Strict-grounded |
| Opportunity generation scoped to a stated problem | Core | Opportunity Agent |
| Gap analysis → learning recommendations | Core | Gap Analysis skill |
| Serendipity / cross-domain suggestions | Enhanced | Concept Expansion skill |
| Proactive insight digest + alerts | Core→Enhanced | "Assistant initiates contact" |

### D. Memory, Feedback & Self-Improvement
| Feature | Tier | Notes |
|---------|------|-------|
| Persistent cross-session memory | MVP | Profile, prefs, state |
| Save an opportunity (`save idea`) | Core | |
| Feedback capture (accept/reject) | Core | Feeds Meta Agent performance tracking |
| Agent performance tracking | Enhanced | Acceptance/correction rate per agent |
| **Meta self-modification proposals (D6)** | Enhanced | Always human-reviewed before taking effect |

### E. Interface & Ops
| Feature | Tier | Notes |
|---------|------|-------|
| Symmetric CLI + Slack | MVP | D2 |
| Async job model (ack < 3s) | MVP | Slack 3s rule |
| Per-role model routing + concurrency guard | MVP | Avoid VRAM thrash |
| Run logs + LangGraph time-travel | Core | Replay any reasoning run |

---

## Self-Improvement Loop (D6)

```
User action / signal
        ↓
Agent output (insight, recommendation, answer)
        ↓
User feedback (accept · reject · correct · save · ignore)
        ↓
Meta Agent evaluation (per-agent acceptance & correction rates)
        ↓
Performance tracking → weak-agent detection
        ↓
Meta proposes a change: a skill edit, a prompt edit, or a new/changed tool wiring
        ↓
 ⏸ HUMAN REVIEW — you approve, edit, or reject the diff. Nothing applies unreviewed.
        ↓
Better future recommendations
```

---

## Success Metrics

1. What am I currently interested in?
2. What am I doing right now?
3. What have I learned recently? What does the research say about X?
4. What projects am I working on?
5. What important developments have I missed?
6. What should I learn next?
7. What should I build/explore next, given my current problem?
8. **Why** are you recommending this? (must cite interest signals + research/graph evidence)
9. How does this connect to my previous work?
10. Which agents are performing poorly, and what change would you propose — and why hasn't it been applied without my say-so?

---

## Implementation Phases

### Phase 0 — Spine (Week 1)
- [ ] Core Engine skeleton; CLI adapter; Ollama routing; Qdrant/SQLite up
- [ ] GitHub activity connector → Interest Agent classification (manual trigger ok)
- [ ] `ask` over the KB returns a cited answer
**Exit:** one activity signal produces a classified interest.

### Phase 1 — Research bridge (Week 2)
- [ ] Interest Agent: full interest graph (strength/decay/emerging/abandoned)
- [ ] **Research Agent**: triggered by classification → arXiv + GitHub connectors → citation graph + knowledge graph (start with papers only)
- [ ] Slack parity; first insight digest
**Exit:** a real interest triggers real research that produces a real graph.

### Phase 2 — Opportunity + Brainstorm (Weeks 3–4)
- [ ] Opportunity Agent: synthesis + gap analysis + ranking over Research Agent's output
- [ ] **Brainstorming Agent**: inquiry (KB, cited) + web search fallback + ideation handoff + research handoff
- [ ] `save idea`; feedback capture
**Exit:** ask anything, get traceable proposals; brainstorm can trigger fresh research.

### Phase 3 — Continuous & self-improving (Ongoing)
- [ ] Medium/news connectors; browser/Slack/calendar activity connectors (privacy-reviewed)
- [ ] Agent performance tracking
- [ ] **Meta self-modification proposals (D6)** — diff-based, human-reviewed
- [ ] Proactive alerts; data aging/pruning

---

## Related Documents

- [personal-assistant.implementation.md](personal-assistant.implementation.md) — build roadmap, repo layout
- [personal-assistant.brainstorm-feature.md](personal-assistant.brainstorm-feature.md) — Brainstorming Agent
- [agent.architecture-guide.md](agent.architecture-guide.md) — how to extend
- [impl/01-cli-and-core-engine.md](impl/01-cli-and-core-engine.md)
- [impl/02-slack-gateway.md](impl/02-slack-gateway.md)
- [impl/03-vector-db-and-storage.md](impl/03-vector-db-and-storage.md)
- [impl/04-daily-research-agent.md](impl/04-daily-research-agent.md) — activity sensing pipeline
- [impl/05-meta-agent-and-skills.md](impl/05-meta-agent-and-skills.md) — Meta, Interest, Opportunity
- [impl/06-research-agent.md](impl/06-research-agent.md) — Research Agent
