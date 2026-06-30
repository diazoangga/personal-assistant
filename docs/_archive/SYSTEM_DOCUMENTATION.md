# Personal Assistant — System Documentation

> A self-directed cognitive engine that learns what you care about from your activity,
> researches it automatically, and builds a knowledge graph — without being asked.

**Source of truth:** this document is generated from the code in `src/`, not from other
design docs. Where the code and the older design notes disagree, the code wins.
**Last updated:** 2026-06-22

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [System Overview](#2-system-overview)
3. [Architecture](#3-architecture)
4. [The Agents (as implemented)](#4-the-agents-as-implemented)
5. [Data Flow](#5-data-flow)
6. [Database Schema](#6-database-schema)
7. [Configuration](#7-configuration)
8. [User Guide](#8-user-guide)
9. [Developer Guide](#9-developer-guide)
10. [Implementation Status](#10-implementation-status)
11. [Known Issues & Gotchas](#11-known-issues--gotchas)

---

## 1. Problem Statement

Knowledge workers face three compounding problems:

| Problem | Consequence |
|---|---|
| **Information overload** | Too many papers, repos, and discussions to track manually; relevant work gets missed. |
| **Context switching** | Manually searching "what's new in X" interrupts deep work and is easy to forget. |
| **Passive tools** | Chatbots and search engines only respond when asked; they don't notice what you're working on and act on it. |

**The goal:** an assistant that is **proactive, not reactive**. It should:

- **Observe** real activity (GitHub events; questions you ask; topics you research),
- **Infer** what you're interested in — and how strongly — without explicit configuration,
- **Act** automatically: research strengthening interests and build a knowledge graph,
- **Decay** gracefully so the model reflects *current* focus, not everything you've ever touched.

This differs from a chatbot: the system can run **continuously** (a daemon), maintains a
**persistent model of you** (a single SQLite store), and makes **autonomous decisions**
about what to research.

---

## 2. System Overview

The codebase is a **multi-agent engine** with **three implemented agents** — Interest,
Research, and a LangGraph **Supervisor** — sharing one unified SQLite store and an LLM
runtime backed by OpenRouter.

```
┌─────────────────────────────────────────────────────────────────────┐
│  INTERFACES                                                           │
│   CLI / REPL (Typer+Rich, src/adapters/cli/app.py)                   │
│   Daemon (24/7, src/daemon/service.py)                               │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────────┐
│  PersonalAssistantEngine (src/main_engine.py) — public API           │
│   high-level methods: ask · brainstorm · research · get_interests ·   │
│   process_activity_signals · run_interest_decay                       │
│                                                                       │
│   ┌────────────────────────────────────────────────────────────┐    │
│   │ Engine (src/core/engine.py) — command router + EventBus      │    │
│   │   submit(cmd) → _route(cmd) → _handle_*  → events            │    │
│   └────────────────────────────────────────────────────────────┘    │
│   registered agents: "interest", "research", "supervisor"            │
└───────┬──────────────────────────────────────────────┬──────────────┘
        │                                                │
┌───────▼────────────┐   ┌───────────────┐   ┌──────────▼──────────────┐
│ Supervisor          │   │ Interest      │   │ UnifiedKnowledgeStore   │
│ (LangGraph          │──▶│ Research      │──▶│ (SQLite: src/store/     │
│  StateGraph)        │   │ agents        │   │  knowledge.py)          │
└─────────────────────┘   └───────────────┘   │ Qdrant (src/store/      │
        ▲                                       │  vector.py)             │
        │ ActivitySignal[]                      └─────────────────────────┘
┌───────┴───────────────────────────────────┐ ┌─────────────────────────┐
│ Connectors (src/daemon/connectors/)        │ │ OpenRouter LLM runtime  │
│   github.py (enabled) · slack.py · browser │ │ (src/llm/openrouter.py) │
└────────────────────────────────────────────┘ └─────────────────────────┘
```

**Tech stack (from `pyproject.toml` and imports):**

| Concern | Implementation |
|---|---|
| Language / packaging | Python, Poetry-managed virtualenv |
| LLM | OpenRouter (`src/llm/openrouter.py`); default model `google/gemma-4-26b-a4b-it:free` |
| Orchestration | LangGraph `StateGraph` (`src/agents/supervisor/agent.py`) |
| Relational store | SQLite via `aiosqlite`, single `knowledge.db` |
| Vector store | Qdrant via `qdrant-client` |
| HTTP | `httpx` (async) — used by arXiv & GitHub connectors and the LLM runtime |
| CLI | Typer + Rich |
| Tests | pytest + pytest-asyncio (`asyncio_mode = auto`) |

---

## 3. Architecture

### 3.1 Command-Driven Core

Every action is an immutable **Command** (`src/core/commands.py`). The base carries `user`:

```python
@dataclass(frozen=True)
class Command:
    user: str

@dataclass(frozen=True)
class ResearchTopic(Command):
    topic: str
    depth: Literal["shallow", "normal", "deep"] = "normal"
```

Defined commands: `Ask`, `Brainstorm`, `ShowInterests`, `ResearchTopic`, `ShowGraph`,
`Opportunities`, `ShowDigest`, `Feedback`, `IngestNow`, `JobStatus`, `Cancel`, `SetPref`,
`Topics`, `Sources`.

`Engine.submit(cmd)` returns a `job_id` immediately and runs the handler as a background
task, publishing events to an **EventBus** that callers subscribe to by `job_id`.

### 3.2 Two Execution Paths (important)

The code has **two distinct ways** work gets done. This is the single most important thing
to understand about how it actually runs:

**Path A — direct method calls (what the CLI uses).**
`pa ask`, `pa brainstorm`, and `pa research` call methods on `PersonalAssistantEngine`
directly; they do **not** go through `Engine.submit`/`_route`:

| CLI command | Calls | What runs |
|---|---|---|
| `pa ask` | `engine.ask()` | LLM answered **directly** via `self._llm.chat(...)`; conversation + interest-batch + knowledge-entry side effects |
| `pa brainstorm` | `engine.brainstorm()` | LLM answered **directly** via `self._llm.chat(...)` |
| `pa research` | `engine.research()` | stores interest @0.85, then calls `research_agent.research(...)` **directly** |

**Path B — command + EventBus (what the daemon uses).**
The daemon submits `ResearchTopic` commands through `engine.submit()`, which routes to
`Engine._handle_research` → the registered `"research"` agent, streaming `Started/Progress/
Result` events.

`Engine._route` maps every command type to a handler, but only some handlers are wired to a
registered agent today:

| Command | Handler | Registered agent? | Status |
|---|---|---|---|
| `ResearchTopic` | `_handle_research` | `"research"` ✅ | Works (used by daemon) |
| `ShowInterests` | `_handle_interests` | `"interest"` ✅ | Works |
| `ShowGraph` | `_handle_graph` | uses store directly ✅ | Works |
| `Ask` | `_handle_ask` | `"brainstorm"` ❌ never registered | Would raise "not initialized" — CLI bypasses it via Path A |
| `Opportunities` / `ShowDigest` | `_handle_opportunities` / `_handle_digest` | `"opportunity"` ❌ | Not implemented |
| `Feedback` / `SetPref` / `Topics` / `Sources` | various | depend on `memory`/`ingest` helpers | Partially wired |

> **Takeaway:** the only agents constructed and registered in
> `PersonalAssistantEngine.initialize()` are **interest**, **research**, and **supervisor**.
> Handlers referencing a `"brainstorm"` or `"opportunity"` agent exist as scaffolding but are
> not reachable in the current build.

### 3.3 Event Types (`src/core/events.py`)

```
Started  → job accepted (kind)
Progress → phase + message (+ optional pct)
Message  → assistant text (+ optional citations)
Result   → terminal: ok + payload
```

The CLI renders these with a Rich `Live` panel; the daemon logs them.

---

## 4. The Agents (as implemented)

Only three agent packages exist under `src/agents/`: `interest/`, `research/`,
`supervisor/`. There is **no** `opportunity`, `brainstorming`, or `meta` package in the
codebase (those appear only in aspirational design docs).

### 4.1 Interest Agent — `src/agents/interest/agent.py`

The engine of proactive behavior. `process_signals(signals, user_id) -> list[ResearchTopic]`:

1. **Classify** signals into topics — hybrid: semantic similarity over cached embeddings,
   LLM fallback (`skills/topic_classification.py`).
2. **Store evidence** — `memory.add_classified_signal(signal_id, topic, confidence, timestamp)`
   into `interest_signal_evidence`.
3. **Detect triggers** (`skills/research_trigger.py`) — emit a `ResearchTopic` when a topic's
   computed strength crosses `strength_threshold` (default 0.3) and it is not on cooldown.

Interest strength is a decayed sum over evidence (`UnifiedKnowledgeStore.get_strength`):

```
strength(topic) = Σ confidenceᵢ · exp(−age_hoursᵢ / decay_hours)      # decay_hours default 720
```

Cooldown is tracked separately in `interest_research_log` (`should_research`,
`mark_researched`), independent of `interests.last_active`.

Read-side helpers: `get_top_interests(min_strength)`, `get_interest_timeline(topic, limit)`.

### 4.2 Research Agent — `src/agents/research/agent.py`

`research(topic, user_id, depth, publish, job_id) -> dict`:

1. **Fetch** papers from arXiv (`tools/arxiv_connector.py`, async `httpx`). Count scales with
   depth via `DEPTH_PAPER_MULTIPLIER = {"shallow":0.5, "normal":1.0, "deep":2.0}` × `max_papers`.
2. **Extract** typed entities per abstract via LLM (`skills/entity_extraction.py`):
   `concept/method/model/task/dataset/metric/framework`, each with a confidence; drop below
   `min_entity_confidence` (0.6).
3. **Deduplicate** — keep highest-confidence per `(name, entity_type)`.
4. **Relate** — second LLM pass infers typed relationships between entities.
5. **Populate** the `UnifiedKnowledgeStore`:
   - papers → `upsert_citation` (`citations`)
   - entities → `upsert_concept` (`concepts`, ID via `compute_concept_id`)
   - paper↔concept mentions → `link_citation_to_concept` (`citation_concept_links`)
   - concept↔concept relations → `add_concept_relationship` (`concept_relationships`)
6. **Summarize** — returns `{topic, papers_found, concepts_extracted, relationships_found,
   summary, elapsed_seconds}`.

Optional `publish`/`job_id` stream `Progress` events (used when invoked via the command path).

### 4.3 Supervisor Agent — `src/agents/supervisor/agent.py`

A compiled LangGraph `StateGraph` (`SupervisorState`). Nodes:
`classify_signals → decide_routing → execute_interest_agent / execute_research_agent →
extract_knowledge → populate_graphs → finalize`, plus `handle_error` with retry.

Edges (from `_build_workflow`):

```
START → classify_signals
classify_signals ─[route]→ execute_interest_agent | execute_research_agent | finalize | handle_error
execute_interest_agent → decide_routing
decide_routing ─[route]→ execute_research_agent | extract_knowledge | finalize | handle_error
execute_research_agent → extract_knowledge → populate_graphs → finalize
handle_error ─[retry?]→ classify_signals | finalize
```

Entry points:
- `process_signals(signal_dicts, user_id)` — runs the full workflow (`workflow.ainvoke`).
- `process_command(command, user_id)` — direct dispatch; for `{"type":"research",
  "params":{"topic":...}}` it seeds `classified_interests` from the topic and runs the
  research node.

Constructed with `(llm, knowledge_store, interest_agent, research_agent, config)`.

---

## 5. Data Flow

### 5.1 Autonomous loop (daemon → interest → research)

`src/daemon/service.py::_run_ingest_cycle` (runs every `ingest_interval_minutes`):

```
enabled connectors.fetch(since=last_ingest)        # github.py (slack/browser if enabled)
        │  ActivitySignal[]
        ▼
engine.process_activity_signals(all_signals)       # main_engine → Supervisor.process_signals
        │  → research topics
        ▼
for topic in research_topics:
        engine.submit(topic)                       # ResearchTopic → _handle_research → Research Agent
        # log: "Research trigger submitted: '<topic>' (depth=..., job_id=...)"
```

The Interest Agent's own contract (`process_signals → list[ResearchTopic]`) is the
mechanism exercised directly by `tests/test_signal_flow.py`.

### 5.2 `ask` flow — `main_engine.ask()`

```
pa ask "Q"
 ├─ get_or_create_session + add user turn + increment question count
 ├─ buffer Q per user; every batch_size (5) questions:
 │     _extract_interests_from_batch(...)  →  upsert each topic as interest @ strength 0.55
 ├─ answer = llm.chat([{user: Q}], model_role="meta")        # direct LLM call
 ├─ add assistant turn
 ├─ _assess_answer_quality(Q, answer)  → score 0.0–1.0 (filler/length filter + LLM rating)
 └─ if score ≥ quality_threshold (0.65): store_knowledge_entry(...)
```

### 5.3 `research` flow — `main_engine.research()`

```
pa research "X" [--depth N]
 ├─ upsert interest "X" @ strength 0.85           # explicit user intent
 └─ research_agent.research("X")  → fetch → extract → relate → populate → summary
```

> **Interest scoring policy (code):** explicit `research` writes **0.85**; inferred topics
> from an `ask` batch write **0.55**. Both feed the same decaying interest model.

---

## 6. Database Schema

Single SQLite file `./data/knowledge.db`, created by `UnifiedKnowledgeStore._create_tables`
(`src/store/knowledge.py`). `PRAGMA foreign_keys = ON`; all access async via `aiosqlite`
with `Row` factory.

### 6.1 Tables

**User memory**

| Table | Key columns |
|---|---|
| `interests` | `id` PK, `label`, `strength` (def 0.5), `embeddings_cached`, `created_at`, `updated_at`, `last_active` |
| `interest_embeddings` | `interest_id` PK→interests, `embedding` BLOB, `model_version` |
| `interest_signal_evidence` | `signal_id`, `topic`, `confidence`, `timestamp`; UNIQUE(signal_id, topic) |
| `interest_research_log` | `topic` UNIQUE, `last_researched_at` (cooldown) |
| `user_profile` | `key` UNIQUE, `value` |
| `opportunities` | `id` PK, `title`, `description`, `relevance_score`, `source`, `url`, `metadata` |
| `activity_log` | `timestamp`, `activity_type`, `description`, `raw_data` |
| `user_stats` | `user_id` PK, `total_questions`, `total_knowledge_entries`, `last_active` |

**Citation graph (papers)**

| Table | Key columns |
|---|---|
| `citations` | `id` PK, `arxiv_id` UNIQUE, `doi` UNIQUE, `title`, `abstract`, `authors` (JSON), `published_date`, `journal`, `categories` (JSON), `citation_count` |
| `citation_relationships` | `source_id`→citations, `target_id`→citations, `relationship_type` |

**Knowledge graph (concepts)**

| Table | Key columns |
|---|---|
| `concepts` | `id` PK (hashed), `label`, `description`, `category` |
| `concept_relationships` | `source_id`/`target_id`→concepts, `relation_type`, `weight` (def 1.0), `evidence`; UNIQUE(source_id, target_id, relation_type) |

**Cross-reference links**

| Table | Joins | Constraint |
|---|---|---|
| `interest_concept_links` | interest ↔ concept (`link_type`, `confidence`) | UNIQUE(interest_id, concept_id) |
| `citation_concept_links` | citation ↔ concept (`relation_type`, `evidence_text`) | UNIQUE(citation_id, concept_id) |
| `opportunity_interest_links` | opportunity ↔ interest (`relevance_score`) | UNIQUE(opportunity_id, interest_id) |

**Conversation & knowledge**

| Table | Key columns |
|---|---|
| `conversation_sessions` | `id` PK, `user_id`, `question_count`, `metadata` |
| `conversation_turns` | `session_id`→sessions, `turn_number`, `role`, `content`, `timestamp`, `metadata` |
| `knowledge_entries` | `id` PK, `question`, `answer`, `quality_score`, `source_session_id`→sessions, `user_id`, `embedded`, `metadata` |

**Indexes:** `interests(strength)`, `interests(label)`, `concepts(label)`,
`citations(published_date)`, `interest_concept_links(interest_id)`,
`citation_concept_links(citation_id)`, plus conversation/knowledge indexes.

### 6.2 Relationships

```
interests ──< interest_concept_links >── concepts ──< citation_concept_links >── citations
   ├──< interest_signal_evidence            └──< concept_relationships >──┘
   ├──< interest_research_log               citations ──< citation_relationships >──┘
   └──< opportunity_interest_links >── opportunities

conversation_sessions ──< conversation_turns
conversation_sessions ──< knowledge_entries
```

### 6.3 Concept IDs & traversal

```python
compute_concept_id(label, category) = sha256(f"{category}:{label.lower().strip()}").hexdigest()[:16]
```

Content-addressed → upserts are idempotent (same concept from two papers → one row).

`relevant_subgraphs(seed_ids=None, interests=None, max_depth=2)` does a bidirectional BFS
over `concept_relationships`, accepting concept IDs or topic-label strings (resolved via
`find_concepts_by_label`), returning `(nodes, edges)` as dict lists.

### 6.4 Vector store

`src/store/vector.py` wraps Qdrant for semantic search / embedding-based interest matching.
It is a separate service (Docker or local) and can be stubbed in tests.

---

## 7. Configuration

### 7.1 Environment (`.env`)

| Variable | Required | Used by |
|---|---|---|
| `OPENROUTER_API_KEY` | ✅ | LLM runtime |
| `GITHUB_TOKEN` | for ingest | GitHub connector |
| `SLACK_BOT_TOKEN` | optional | Slack connector (disabled by default) |

`_load_config()` (`src/adapters/cli/app.py`) loads `config/settings.toml` via `toml` and
merges `OPENROUTER_API_KEY` / `GITHUB_TOKEN` from the environment.

### 7.2 `config/settings.toml` (selected)

```toml
[llm]
meta_model      = "google/gemma-4-26b-a4b-it:free"
reasoning_model = "google/gemma-4-26b-a4b-it:free"
embedding_model = "nvidia/llama-nemotron-embed-vl-1b-v2:free"

[storage]
knowledge_db = "./data/knowledge.db"
qdrant_host  = "localhost"
qdrant_port  = 6333

[agents.interest]
batch_size              = 5      # questions per interest-extraction batch
strength_threshold      = 0.3    # auto-research trigger
research_cooldown_hours = 2
auto_research_enabled   = true

[agents.research]
arxiv_max_results     = 10
entity_extraction_max = 20
min_entity_confidence = 0.6

[knowledge]
quality_threshold     = 0.65     # min quality to store a Q&A
decay_half_life_hours = 720

[daemon]
check_interval_seconds  = 60
ingest_interval_minutes = 15
log_file = "./data/daemon.log"

[connectors.github]   # enabled (true)
[connectors.slack]    # enabled = false
[connectors.browser]  # enabled = false
```

> Note: some keys appear under both `[ingest]` and `[agents.*]` in the TOML (e.g. arXiv
> results). The Research Agent reads `agents.research.*`; the legacy ingest pipeline reads
> `[ingest]`.

---

## 8. User Guide

### 8.1 Install

```bash
poetry install
cp .env.example .env        # set OPENROUTER_API_KEY (+ GITHUB_TOKEN for ingest)
poetry shell                # optional
```

### 8.2 CLI commands (`src/adapters/cli/app.py`)

Run via the `pa` entry point (or `poetry run python -m src.adapters.cli.app`):

| Command | Description |
|---|---|
| `pa ask "<question>"` | Answer a question; buffers it toward interest extraction |
| `pa research "<topic>" [-d N]` | Research a topic (`-d/--depth` 1–5); records interest @0.85 |
| `pa brainstorm "<topic>"` | Generate ideas/angles on a topic |
| `pa interests [--all]` | Show interests (default min strength 0.3; `--all` = 0.0) |
| `pa ingest [-c github]` | Pull activity signals from a connector now |
| `pa status` | Show config/engine readiness |
| `pa repl` | Interactive loop: ask / brainstorm / research / ingest / interests / status / exit |

**Daemon (`pa daemon ...`):**

| Command | Description |
|---|---|
| `pa daemon start [-f]` | Start daemon (`-f` foreground) |
| `pa daemon stop [-f]` | Stop (`-f` force/SIGKILL) |
| `pa daemon status` | Running? |
| `pa daemon logs [-f] [-n N]` | View/tail logs |
| `pa daemon clear-logs` | Reset logs |

### 8.3 Workflows

**Manual research**

```bash
pa research "retrieval augmented generation" --depth 3
pa interests          # appears @ ~0.85
```

**Learn from questions** (interest extraction fires every 5th question)

```bash
pa ask "What is a transformer?"
pa ask "Explain attention"
pa ask "What is a KV cache?"
pa ask "How does RoPE work?"
pa ask "What is flash attention?"   # batch extraction → interests @ ~0.55
pa interests --all
```

**Autonomous**

```bash
pa daemon start
pa daemon logs --follow      # watch: classify → strength → "Research trigger submitted"
```

---

## 9. Developer Guide

### 9.1 Testing

```bash
# Full suite minus the network-prone test_core.py
poetry run pytest tests/ --ignore=tests/test_core.py -v

# Targeted
poetry run pytest tests/test_phase1_integration.py -v   # research flow end-to-end
poetry run pytest tests/test_arxiv_connector.py -v
poetry run pytest tests/test_entity_extraction.py -v
poetry run pytest tests/test_supervisor.py -v
poetry run pytest tests/test_signal_flow.py -v

poetry run pytest tests/ --cov=src                       # coverage
```

> Always use `poetry run pytest` — `pytest-asyncio`/`pytest-cov` live only in the Poetry venv.

### 9.2 Quality

```bash
poetry run black src/ tests/
poetry run ruff check src/
poetry run mypy src/
```

### 9.3 Layout (actual)

```
src/
├── core/            engine.py · commands.py · events.py · bus.py · jobs.py · signals.py
├── agents/
│   ├── interest/    agent.py · skills/{topic_classification,research_trigger} · tools/signal_formatting
│   ├── research/    agent.py · skills/entity_extraction · tools/arxiv_connector
│   └── supervisor/  agent.py · types.py · skills/routing · tools/
├── store/           knowledge.py (UnifiedKnowledgeStore) · vector.py (Qdrant) · memory.py
├── daemon/          service.py · connector_base.py · connectors/{github,slack,browser}.py · manager.py
├── ingest/          pipeline.py (legacy) · connectors/
├── llm/             openrouter.py
├── skills/          classification · retrieval · summarization · topic_extraction
├── adapters/cli/    app.py (Typer/Rich)
└── main_engine.py   PersonalAssistantEngine (public API)
```

### 9.4 Extending

- **Connector:** subclass `ActivityConnector` (`src/daemon/connector_base.py`), implement
  `async fetch(since)`, register in `PersonalAssistantDaemon._initialize_connectors`, add a
  `[connectors.*]` config block.
- **Command:** add a frozen dataclass in `commands.py`, a `_handle_*` on `Engine`, a route in
  `_route`, and publish events.
- **Agent:** construct it in `PersonalAssistantEngine.initialize()` and call
  `engine.register_agent(name, agent)`.

---

## 10. Implementation Status

Derived from what is constructed/registered in `PersonalAssistantEngine.initialize()` and
present under `src/agents/`:

| Component | State |
|---|---|
| Interest Agent | ✅ Implemented & registered |
| Research Agent | ✅ Implemented & registered |
| Supervisor (LangGraph) | ✅ Implemented & registered |
| UnifiedKnowledgeStore (SQLite) | ✅ Full schema + CRUD + graph traversal |
| GitHub connector | ✅ Real (`httpx` against GitHub events API) |
| Slack / Browser connectors | Present, **disabled** by default |
| arXiv connector | ✅ Real (`httpx`, HTTPS) |
| Qdrant vector store | ✅ Wrapper present (requires running Qdrant) |
| CLI + REPL + Daemon | ✅ Implemented |
| Brainstorming / Opportunity / Meta agents | ❌ Not implemented (only handler scaffolding in `Engine`) |

---

## 11. Known Issues & Gotchas

1. **`Ask`/`Opportunities` command handlers are unreachable.** `Engine._handle_ask`
   references an unregistered `"brainstorm"` agent and `_handle_opportunities` an
   unregistered `"opportunity"` agent; both raise "not initialized" if invoked via
   `submit()`. The CLI sidesteps this by calling `main_engine.ask()`/`.brainstorm()`
   directly (Path A).
2. **`process_activity_signals` vs daemon expectation.** `main_engine.process_activity_signals`
   delegates to `Supervisor.process_signals`, which returns a workflow-state dict, while the
   daemon loop iterates the return value expecting `ResearchTopic` objects to `submit()`.
   The directly-tested contract is `InterestAgent.process_signals → list[ResearchTopic]`;
   verify this path when enabling the daemon end-to-end.
3. **`test_core.py` can hang** on network-bound tests — exclude with
   `--ignore=tests/test_core.py`.
4. **pytest-asyncio is venv-only** — always `poetry run pytest`.
5. **Naive vs. aware datetimes.** Some paths (`get_strength`, a few `test_store` cases) mix
   offset-naive and offset-aware datetimes → `TypeError` in isolation. Signals should carry
   the original activity `timestamp`, not `datetime.utcnow()`, for decay to be correct.
6. **Cooldown decoupling.** Research cooldown lives in `interest_research_log`, separate from
   `interests.last_active`.
7. **Qdrant required for vector search** — run it (Docker/local) or stub in tests.
8. **arXiv needs HTTPS** — connector uses `https://export.arxiv.org/api/query` (HTTP 301 is
   not auto-followed by `httpx`).

---

*Generated from the `src/` codebase. Cross-references to older design notes
(`docs/orchestrator-design.md`, `docs/supervisor-architecture.md`,
`docs/agent.architecture-guide.md`) may describe planned, not current, behavior.*
