---
title: Implementation Plan Overview
created: 2026-06-21
updated: 2026-06-21
version: 1.0.0
status: Reference
tags:
  - implementation
  - overview
---

# Implementation Plan Overview

Visual summary of the Personal Assistant implementation plan. Full details in **[plans.implementation-comprehensive.md](plans.implementation-comprehensive.md)**.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    User Interfaces                              │
│  ┌──────────────────┐                  ┌──────────────────┐   │
│  │   CLI (Typer)    │◄──────────────────►│ Slack (Bolt)    │   │
│  └──────────────────┘                  └──────────────────┘   │
│           △                                     △              │
└───────────┼─────────────────────────────────────┼──────────────┘
            │                                     │
            └─────────────────┬───────────────────┘
                              ▼
        ┌─────────────────────────────────────┐
        │    Core Engine (Command/Events)     │
        │  - Submit command → get job_id      │
        │  - Stream events async              │
        └────────────┬────────────────────────┘
                     │
        ┌────────────▼────────────────────────────────────────┐
        │         Agent Orchestration Layer                   │
        │  (LangGraph subgraphs)                              │
        │                                                     │
        │  ┌──────────┐ ┌──────────┐ ┌──────────┐           │
        │  │ Interest │ │Research  │ │Opportun. │           │
        │  │ Agent    │ │Agent     │ │Agent     │           │
        │  └──────────┘ └──────────┘ └──────────┘           │
        │      △           △              △                  │
        │      │           │              │                  │
        │  ┌─────────────────────────────────┐              │
        │  │  Meta Agent (Orchestrator)      │              │
        │  │  Brainstorming Agent (Interactive)│            │
        │  └─────────────────────────────────┘              │
        └────────────┬────────────────────────────────────────┘
                     │
        ┌────────────▼────────────────────────────────────────┐
        │           Skills Layer (Transforms)                │
        │  - Topic extraction                               │
        │  - Classification, Retrieval, Ranking             │
        │  - Entity extraction, Graph construction          │
        │  - Summarization, Gap analysis, Concept synthesis │
        └────────────┬────────────────────────────────────────┘
                     │
        ┌────────────▼────────────────────────────────────────┐
        │            Storage & Tools Layer                   │
        │  ┌──────────────┐ ┌──────────────────┐            │
        │  │ Vector DB    │ │ SQLite Memory    │            │
        │  │ (Qdrant)     │ │ (Graph/Interests)│            │
        │  └──────────────┘ └──────────────────┘            │
        │  ┌──────────────┐ ┌──────────────────┐            │
        │  │ LLM (OpenRouter)│ │ External APIs  │           │
        │  │ Gemma4-31B   │ │ (arXiv, GitHub, │            │
        │  └──────────────┘ │  Medium, News)   │            │
        │                   └──────────────────┘            │
        └─────────────────────────────────────────────────────┘
                     ▲
        ┌────────────┴───────────────────────────────────────┐
        │      Activity Sensing Pipeline (Ingest)           │
        │                                                   │
        │  ┌──────────┐ ┌──────────┐ ┌──────────┐        │
        │  │  GitHub  │ │ VSCode   │ │ File     │        │
        │  │Connector │ │Connector │ │Connector │        │
        │  └──────────┘ └──────────┘ └──────────┘        │
        │       △           △             △              │
        │       └───────────┴─────────────┘              │
        │       (Optional: Browser, Slack, Calendar)    │
        └─────────────────────────────────────────────────┘
```

## Implementation Roadmap

### Phase 0: Core Signal Flow (Week 1)
**Goal:** GitHub commit → topic → stored signal

```
┌─ 0.1: Signal → Interest Integration
│         (5–7 days)
│         Define ActivitySignal, store classifications
│
├─ 0.2: VSCode Connector
│         (5 days)
│         Monitor file edits, extensions, debugging
│
├─ 0.3: File System Connector
│         (3 days)
│         Track document changes, directory structure
│
└─ 0.4: Signal Aggregation & Windowing
          (5 days)
          Group signals, detect spikes

Exit Criteria:
  ✓ GitHub commit emitted as ActivitySignal
  ✓ Signal classified into topic
  ✓ Classification stored in interest graph
```

### Phase 1: Interest & Research (Weeks 2–3)
**Goal:** Interest triggers research; graphs populated

```
┌─ 1.1: Interest Model Implementation
│         (8 days)
│         Strength decay, trajectory, relationships
│
├─ 1.2: Research Agent Trigger Logic
│         (6 days)
│         Detect new/strengthened interests, rate limit
│
├─ 1.3: Knowledge Graph Integration
│         (10 days)
│         Citation + Knowledge graphs, novelty scoring
│
└─ 1.4: Research Agent
          (15 days)
          arXiv, GitHub, Medium, entity extraction

Exit Criteria:
  ✓ Interest strength computed correctly
  ✓ New interest triggers ResearchTopic command
  ✓ Research Agent finds papers + concepts
  ✓ Citation/Knowledge graphs populated
```

### Phase 2: Opportunity & Brainstorm (Weeks 4–5)
**Goal:** Brainstorm loop end-to-end

```
┌─ 2.1: Opportunity Agent Synthesis
│         (11 days)
│         Gap analysis, ranking, novelty scoring
│
└─ 2.2: Brainstorming Agent
          (15 days)
          Multi-turn sessions, KB + web search, Research routing

Exit Criteria:
  ✓ Opportunities generated from interests + research
  ✓ User can brainstorm with KB retrieval
  ✓ Web search invoked for current info
  ✓ Research Agent triggered mid-session
  ✓ Sessions persist across restarts
```

### Phase 3: Advanced & Polish (Weeks 6–8+)
**Goal:** Continuous operation, self-improvement, production-ready

```
┌─ 3.1: Digest Generation (7 days)
├─ 3.2: Meta Agent Performance Review (9 days)
├─ 3.3: System Integration / Service (5 days)
├─ 3.4: State Persistence & Recovery (5 days)
├─ 3.5: Browser Connector [optional] (6–8 days)
├─ 3.6: Monitoring & Observability (4–7 days)
└─ 3.7: Documentation (7 days)

Core Exit Criteria:
  ✓ Daemon runs 24/7 (Windows/macOS/Linux)
  ✓ Daily digest delivered to Slack + CLI
  ✓ Feedback collected, improvements proposed
  ✓ System survives crashes, recovers state
  ✓ Metrics + logs visible; system health inspectable

Optional/Deferred:
  ⏳ Browser connector (complex, privacy considerations)
  ⏳ Web UI dashboard (nice-to-have)
```

## Feature Complexity Matrix

```
            Low Complexity    Medium Complexity    High Complexity
Phase 0     0.2, 0.3, 0.4   0.1                  —
Phase 1     1.2              1.1, 1.3             1.4
Phase 2     —                2.1                  2.2
Phase 3     3.3, 3.4         3.1, 3.2, 3.6        3.5, 3.7
```

### Quick Win: Phase 0.2 & 0.3
- VSCode + File System connectors (8 days)
- Independent of interest model
- Ship working connectors early
- De-risk the foundation

## Key Design Decisions (D1–D6)

| Decision | Impact | Status |
|----------|--------|--------|
| **D1: OpenRouter + Gemma4-31B** | Free LLM tier; no local VRAM needed | ✅ Locked |
| **D2: Symmetric CLI/Slack** | One engine, two interfaces | ✅ Locked |
| **D3: LangGraph orchestration** | Checkpointing, state machines | ✅ Locked |
| **D4: Agent/Skill/Tool separation** | Prevent feature bloat | ✅ Locked |
| **D5: Signal-driven, continuous** | Proactive, not reactive | ✅ Locked |
| **D6: Human-reviewed self-modification** | Safety gate on autopilot | ✅ Locked |

## Effort Breakdown

```
Phase 0:  18 days (1 week)
Phase 1:  39 days (2–3 weeks)
Phase 2:  26 days (2 weeks)
Phase 3:  42–50 days (3+ weeks)
────────────────────────────
Total:   125–133 days ≈ 8–12 weeks (solo, full engagement)
```

By component:
```
Connectors:        18 days (GitHub, VSCode, File, Browser)
Agents:            70 days (Interest, Research, Opportunity, Brainstorm, Meta)
Storage:           12 days (Graph, Interest models)
Integration:       15 days (System service, persistence, observability)
Documentation:      7 days
Testing:           15 days (across all phases)
```

## Risk Summary

```
High Risk (mitigate actively):
  • Scope creep → Strict phase gates
  • OpenRouter API changes → Pin versions, monitoring
  • Signal noise → High confidence thresholds

Medium Risk (watch closely):
  • LangGraph complexity → Unit-test each node
  • Context window overflow → Sliding window implementation
  • Browser extension fragility → Use stable APIs only

Low Risk (documented):
  • Data corruption → Transactions, checkpointing
  • Privacy concerns → Local-only design, no telemetry
```

## Success Milestones

| Milestone | When | What's Done | You Can Do |
|-----------|------|-----------|-----------|
| **M0** | Week 1 | GitHub → topic → stored signal | `pa ask` works with KB |
| **M1** | Weeks 2–3 | Interest triggers Research; graphs populated | `pa research <topic>` manual trigger |
| **M2** | Weeks 4–5 | Brainstorm loop end-to-end | `pa brainstorm` REPL, Slack integration |
| **M3** | Weeks 6–8+ | Daemon runs 24/7; daily digest; feedback loop | Full autonomous system |

## Getting Started

1. **Read:** [IMPLEMENTATION_QUICK_INDEX.md](IMPLEMENTATION_QUICK_INDEX.md) (5 min)
2. **Deep dive:** [plans.implementation-comprehensive.md](plans.implementation-comprehensive.md) (1–2 hours)
3. **Start Phase 0.1:** Interest Agent signal integration (5–7 days)
4. **Parallelize Phase 0.2–0.3:** Connectors (3–5 days)
5. **Review Phase 0 exit criteria:** Complete signal flow end-to-end

## Document Index

- **[plans.implementation-comprehensive.md](plans.implementation-comprehensive.md)** — Full implementation plan (2,133 lines)
- **[IMPLEMENTATION_QUICK_INDEX.md](IMPLEMENTATION_QUICK_INDEX.md)** — Navigation guide (features by phase, complexity, dependencies)
- **[IMPLEMENTATION_OVERVIEW.md](IMPLEMENTATION_OVERVIEW.md)** — This file (visual summary)
- **[personal-assistant.plans.md](personal-assistant.plans.md)** — Architecture & vision
- **[personal-assistant.implementation.md](personal-assistant.implementation.md)** — Roadmap (M0–M3)
- **[agent.architecture-guide.md](agent.architecture-guide.md)** — Agent/Skill/Tool extension guide

---

**Status:** Ready to implement  
**Confidence:** High (based on locked architecture, proven storage layer, existing CLI)  
**Last Updated:** 2026-06-21
