---
title: Personal Assistant — Comprehensive Implementation Plan
created: 2026-06-21
updated: 2026-06-21
version: 1.0.0
status: Draft
tags:
  - implementation
  - planning
  - comprehensive
changelog:
  - version: 1.0.0
    date: 2026-06-21
    changes: "Initial comprehensive implementation plan covering all 18 features across 4 phases with scope, dependencies, design, complexity, and risk analysis"
audience: Engineering lead and solo developer for Personal Assistant project
reference:
  - docs/personal-assistant.plans.md
  - docs/personal-assistant.implementation.md
  - docs/agent.architecture-guide.md
---

> When this document is updated, refresh the `updated` field and append a changelog entry.

# Personal Assistant — Comprehensive Implementation Plan

## Executive Summary

This document provides a complete, phase-by-phase implementation plan for the Personal Assistant cognitive engine. It covers 18 features organized across 4 phases, from foundational signal flow (Phase 0) through advanced system integration and optimization (Phase 3).

**Current Status:** Foundation complete (Week 1). Storage, CLI, and core engine contracts are implemented. Connectors and signal flow logic are next.

**Estimated Total Effort:** 8–12 weeks solo development at full engagement.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Phase 0: Core Signal Flow (Foundation)](#phase-0-core-signal-flow-foundation)
3. [Phase 1: Interest & Research Agent Integration](#phase-1-interest--research-agent-integration)
4. [Phase 2: Opportunity & Brainstorming](#phase-2-opportunity--brainstorming)
5. [Phase 3: Advanced Features & Optimization](#phase-3-advanced-features--optimization)
6. [Cross-Cutting Concerns](#cross-cutting-concerns)
7. [Success Criteria](#success-criteria)
8. [Risk Register](#risk-register)

---

## Project Overview

### System Architecture at a Glance

```
Signals (GitHub, Browser, VSCode, FS)
    ↓
Activity Sensing Pipeline (ingest/)
    ↓
Signal Classification & Aggregation
    ↓
Interest Agent (maintenance + prioritization)
    ↓
Research Agent (triggered on interest changes)
    ↓
Knowledge/Citation Graphs
    ↓
Opportunity Agent (synthesis & recommendations)
    ↓
Meta Agent (orchestration, feedback, self-improvement)
    ↓
Brainstorming Agent (interactive, KB + web search)
    ↓
Digest & Alerts (Slack/CLI)
```

### Key Principles

1. **Continuous sensing**: System runs on schedule, not just on user demand
2. **Signal-driven**: All agent decisions flow from signals (GitHub activity, file changes, etc.)
3. **Strict separation**: Agents decide, Skills compute, Tools execute
4. **Human-reviewed self-modification**: Meta Agent proposes changes, humans approve
5. **Privacy-first**: Selective filtering before any cloud API call
6. **Symmetric interfaces**: CLI and Slack reach the same engine

---

## Phase 0: Core Signal Flow (Foundation)

**Timeline:** Week 1 (2026-06-21 to 2026-06-27)

**Goal:** Implement the complete signal pipeline from activity sources through classification, aggregation, and storage. Verify that one complete signal flow (e.g., GitHub commit → topic → stored signal) works end-to-end.

### Feature 0.1: Signal → Interest Agent Integration

**Overview**

The Interest Agent consumes `ActivitySignal` objects from connectors, classifies activity into interests/topics, scores interest strength, updates the interest model over time, and triggers the Research Agent when interests are new or strengthened.

**Scope & Boundaries**

- Accept raw `ActivitySignal` objects (user, timestamp, activity_type, data_dict)
- Invoke the Topic Extraction skill to tag signals with 0..N topics and confidence scores
- Build a time-indexed interest history in the memory store
- Compute interest decay (older signals matter less than recent)
- Identify when an interest is new or has risen in strength — trigger Research Agent
- Do **not** decide what research to do (that's Research Agent's job)
- Do **not** modify signal data (ingest pipeline owns that)

**Dependencies**

- ✅ Storage layer (`store/memory.py` — already has interest graph tables)
- ✅ Core engine (`core/engine.py` — already has job submission)
- ✅ Topic Extraction skill (`skills/topic_extraction.py` — already implemented)
- **Skills needed**: Classification, Trend Detection

**High-Level Design Approach**

1. Define `InterestSignal` dataclass (topic, confidence, source_signal_id, timestamp)
2. Interest Agent consumes signals on a schedule (e.g., hourly rollup)
3. For each signal:
   - Extract topics via skill
   - Store (topic, confidence, timestamp) in interest graph as a node/edge
   - Compute interest strength: weighted recent signals (exponential decay)
   - Check if strength crossed a threshold (new or strengthened) → emit `ResearchTopic` command
4. Update interest model every 6 hours (configurable in `settings.toml`)
5. Maintain a "last researched" timestamp per topic to avoid re-triggering

**Data Models & Schemas**

```python
# src/core/commands.py (already has this)
@dataclass(frozen=True)
class ResearchTopic(Command):
    topic: str
    strength: float        # 0-1, how confident/strong
    source_signal_id: str  # why we're researching (for provenance)
    depth: str = "normal"  # or "deep"

# src/store/memory.py (extend InterestGraph)
class InterestGraph:
    def add_signal(self, topic: str, confidence: float, user: str, timestamp: datetime) -> None:
        """Add a classification to the interest timeline."""
    
    def get_strength(self, topic: str, user: str, decay_hours: int = 720) -> float:
        """Compute strength: sum of recent signals, exponentially decayed."""
    
    def get_strengthened_topics(self, user: str, threshold_increase: float = 0.1) -> list[str]:
        """Topics whose strength increased in the last window (triggers research)."""
    
    def mark_researched(self, topic: str, user: str) -> None:
        """Update last_researched timestamp to avoid re-triggering within a cooldown."""

# src/ingest/signal.py (define the signal contract)
@dataclass
class ActivitySignal:
    user: str
    timestamp: datetime
    activity_type: str        # "commit", "file_edit", "compile", etc.
    source: str               # "github", "vscode", "browser", "filesystem"
    data: dict                # activity-specific: {"repo": "...", "message": "..."}
    signal_id: str = field(default_factory=lambda: str(uuid4()))
```

**External API/Service Dependencies**

- None (all signals are local, classification is local)

**Implementation Complexity**

**Medium** — requires integrating signal flow with a decision point (when to trigger Research), but the individual pieces (signal storage, decay computation) are straightforward.

**Estimated Effort**

- Signal dataclass & repository methods: 2–3 days
- Interest Agent LangGraph subgraph: 2–3 days
- Integration tests: 1 day
- **Total: 5–7 days**

**Success Criteria**

1. A GitHub commit signal is classified into at least 1 topic
2. Interest strength is computed correctly (recent signals weighted higher)
3. When a topic strength increases by >10%, a `ResearchTopic` command is emitted
4. Same topic does not trigger multiple times within a 24-hour window

**Potential Risks**

1. **Threshold tuning**: Initial decay constants and trigger thresholds may be too aggressive or too conservative. *Mitigation:* ship with conservative defaults (long decay, high threshold); iterate based on real signal flow.
2. **Signal → topic mapping**: If topic extraction is noisy, interest model is noisy. *Mitigation:* include confidence scores; require `confidence > 0.6` to count toward strength.
3. **Feedback loop**: If Research Agent finds nothing new, should interest strength decrease? *Mitigation:* keep Interest & Research decoupled; feedback (if research was relevant) goes to Meta Agent, not back to Interest.

**Related Documentation**

- [Topic Extraction Skill](skills/topic_extraction.py) — extracts labels from text
- [Classification Skill](skills/classification.py) — activity type detection
- [Interest Graph Schema](docs/impl/03-vector-db-and-storage.md#interest-graph-schema)

---

### Feature 0.2: VSCode Connector

**Overview**

A connector that monitors file edits, extensions used, debugging sessions, and language/framework switches in real-time from VSCode, emitting `ActivitySignal` objects into the ingest pipeline.

**Scope & Boundaries**

- Real-time file change detection via VSCode extension or file system watcher
- Track file path, extension, language ID, edit timestamp
- Detect debugging sessions (breakpoints, debug console activity)
- Detect language/framework switches (e.g., opening a Rust file after months of Python)
- Optional: detect current location in codebase (top-level module being edited)
- Do **not** capture file contents (privacy)
- Do **not** track cursor position or keystroke frequency

**Dependencies**

- **Extension approach**: VSCode Extension API (TypeScript)
  - Requires separate TypeScript project in `vscode-extension/`
  - Sends events to a local HTTP endpoint or IPC
  - Complex but very accurate
- **File system approach**: File watcher on user's workspace directories
  - Poll workspace dirs every 5 seconds
  - Watch for `.git` hooks or similar
  - Simpler, less accurate, privacy-respecting

*Recommendation: Start with file-system approach (M0); VSCode extension is deferred to Phase 3.*

**High-Level Design Approach**

1. Configure watched directories in `settings.toml` (e.g., `~/projects`, `~/work`)
2. Periodic file-system scan (every 5 seconds):
   - Hash file mtimes and extension lists
   - Compare to last scan; detect new/modified files
   - For each change, emit an `ActivitySignal`:
     - `activity_type`: "file_edit" | "debug_session" | "extension_install" | "lang_switch"
     - `data`: {path, language, previous_language, editor_time_minutes}
3. Detect debugging:
   - Watch for `.gdb`, `.vscode/launch.json`, `pytest` temp dirs
   - Heuristic: if project has recent `.pytest-cache`, likely debugging happened
4. Language switch detection:
   - Track last-edited file extension per project
   - When extension changes significantly (e.g., no Rust for 30 days, now editing `.rs`), emit signal
5. Emit hourly rollup: `{active_extensions, active_languages, debug_sessions_count}`

**Data Models & Schemas**

```python
# src/ingest/connectors/vscode.py
class VSCodeConnector(Connector):
    """File-system watcher on user workspace."""
    
    async def fetch(self) -> list[ActivitySignal]:
        """
        Scan watched dirs; return signals for changes since last scan.
        
        Returns:
            List of ActivitySignal with activity_type in:
            - "file_edit": data = {path, language, editor_time}
            - "lang_switch": data = {from_lang, to_lang, context}
            - "debug_session": data = {project, framework}
        """
```

**External API/Service Dependencies**

- None (pure file-system operations)

**Implementation Complexity**

**Low** — straightforward file watcher; challenge is accurate language detection.

**Estimated Effort**

- File watcher + hashing: 2 days
- Language detection heuristics: 1 day
- Debug session detection: 1 day
- Tests (mock file system): 1 day
- **Total: 5 days**

**Success Criteria**

1. File edits are detected within 5 seconds
2. A user opens a `.rs` file for the first time in 30 days → `lang_switch` signal emitted
3. Two consecutive Python edits do not duplicate signals
4. Zero false positives on debug detection (no false signals on config file edits)

**Potential Risks**

1. **False positives**: Build artifacts, temp files trigger spurious signals. *Mitigation:* filter by `.gitignore` and common exclusions (`node_modules`, `.pytest-cache`).
2. **Privacy**: Watching entire workspace can leak sensitive paths. *Mitigation:* opt-in configuration; never log full paths, only relative.
3. **Accuracy**: Language detection by extension is brittle (`.t` files could be Perl or Tera). *Mitigation:* look at file header comment (shebang or lang marker) to disambiguate.

**Related Documentation**

- [Ingest Pipeline Architecture](docs/impl/04-daily-research-agent.md#ingest-pipeline)
- [Connector Interface](src/ingest/connectors/__init__.py)

---

### Feature 0.3: File System Connector

**Overview**

Monitor document changes, file creation/deletion, and directory structure changes in user's working directories. Emit signals for significant activity (e.g., new project directory, document refactor).

**Scope & Boundaries**

- Track file creation/deletion in configured directories
- Monitor file size changes (proxy for refactoring/rewriting)
- Detect directory structure changes (new subdirs, bulk moves)
- Focus on directories with version control (`.git`, `.hg`) or project markers (`.vscode`, `package.json`)
- Do **not** capture file contents
- Do **not** track every keystroke; batch into hourly summaries

**Dependencies**

- File system watcher (same as VSCode connector, can share implementation)
- Git history access (optional, for more context)

**High-Level Design Approach**

1. Extend VSCode connector's file watcher to track document-oriented metrics:
   - Size deltas (if file grew >50%, probably new content, not refactor)
   - Deletion count (bulk cleanup → possible interest shift)
   - Directory depth changes (new project structure → investigation)
2. Emit signals:
   - `activity_type`: "document_created" | "document_refactored" | "directory_restructured"
   - `data`: {path, size_before, size_after, deleted_count}
3. Batch into hourly summaries per directory:
   - Total edits, creations, deletions
   - Infer activity level (quiet, moderate, active, intense)

**Data Models & Schemas**

```python
# src/ingest/connectors/filesystem.py
@dataclass
class FileSystemSignal(ActivitySignal):
    activity_type: Literal["document_created", "document_refactored", "directory_restructured"]
    # data includes: path, size_before, size_after, deleted_count, activity_level
```

**External API/Service Dependencies**

- None

**Implementation Complexity**

**Low** — builds on file watcher; new heuristics for size changes and bulk operations.

**Estimated Effort**

- Extend VSCode watcher with size tracking: 1 day
- Heuristics (refactor detection, restructure detection): 1 day
- Tests: 1 day
- **Total: 3 days**

**Success Criteria**

1. A new file is detected and signal emitted within 5 seconds
2. A file growing from 1KB to 50KB (refactor) is classified as `document_refactored`
3. Deleting 10+ files in one directory in one hour triggers `directory_restructured` signal
4. No spurious signals on lock/temp files

**Potential Risks**

1. **Build artifacts**: Compilation outputs can look like refactoring. *Mitigation:* ignore common build dirs (`dist/`, `build/`, `.o`).
2. **Diff inference**: Size change doesn't capture semantic change. *Mitigation:* this is acceptable; Interest Agent will classify based on topic extraction; if size change is uninteresting, topic score will be low.

**Related Documentation**

- [File System Monitoring](docs/impl/04-daily-research-agent.md#activity-sources)

---

### Feature 0.4: Signal Aggregation & Windowing

**Overview**

Group signals by time windows (hourly, daily), aggregate activity by topic/domain, surface high-level patterns, and detect activity spikes.

**Scope & Boundaries**

- Group signals into 1-hour, 6-hour, and 24-hour windows
- Aggregate by source (GitHub, VSCode, file system)
- Aggregate by inferred topic (from topic extraction)
- Count and score: commits, file edits, debugging sessions, new files
- Detect spikes: if activity in a window is 2x+ the 7-day rolling average
- Emit `AggregatedSignal` for downstream agents
- Do **not** do statistical analysis (leave that to agents)

**Dependencies**

- ✅ Signal types from Phase 0.1–0.3
- ✅ Classification skill (topic extraction)
- Storage: ingest signals table with `window_id` column

**High-Level Design Approach**

1. `SignalAggregator` service (runs every hour):
   - Query raw signals from last 1-hour window
   - Group by source + inferred topic
   - Compute counts, sums, unique users
   - Detect spikes (compare to 7-day rolling avg)
   - Emit `AggregatedSignal` event
2. Store aggregated signals in a separate table (for trend analysis)
3. Expose API:
   - `get_signals(user, window, topic)` → list[AggregatedSignal]
   - `get_activity_level(user, days=7)` → "quiet" | "moderate" | "active" | "intense"

**Data Models & Schemas**

```python
# src/ingest/aggregation.py
@dataclass
class AggregatedSignal:
    user: str
    window_start: datetime
    window_duration: timedelta  # 1h, 6h, 24h
    source: str                 # "github" | "vscode" | "filesystem" | "all"
    topic: str | None           # topic extracted from all signals in window
    signal_count: int
    activity_score: float       # 0-1
    spike_detected: bool        # 2x+ rolling 7-day avg
    details: dict               # source-specific: commits, files, lines, etc.

class SignalAggregator:
    async def aggregate(self, user: str, window_hours: int = 1) -> list[AggregatedSignal]:
        """Group and score signals for a user in a time window."""
    
    async def detect_spikes(self, user: str, days_baseline: int = 7) -> list[AggregatedSignal]:
        """Return signals where activity spiked 2x+ baseline."""
```

**External API/Service Dependencies**

- None

**Implementation Complexity**

**Low** — straightforward aggregation and statistical calculation.

**Estimated Effort**

- Aggregation logic: 2 days
- Spike detection: 1 day
- Storage & queries: 1 day
- Tests: 1 day
- **Total: 5 days**

**Success Criteria**

1. Signals from 1 hour are aggregated into 1 AggregatedSignal per topic
2. If user has 5 commits in 1 hour vs 2 commits/hour average, spike is detected
3. Activity level escalates from "quiet" to "intense" as signal count increases

**Potential Risks**

1. **Baseline skew**: If user usually inactive, even modest activity spikes. *Mitigation:* require minimum absolute count (>3 signals) before spiking, or use median instead of mean.

**Related Documentation**

- [Signal Flow Pipeline](docs/impl/04-daily-research-agent.md)

---

## Phase 1: Interest & Research Agent Integration

**Timeline:** Weeks 2–3 (2026-06-28 to 2026-07-11)

**Goal:** Build the Interest Agent to classify activity, trigger Research Agent, and populate a knowledge graph with research findings. By end of Phase 1, an Interest classification should trigger real research that produces a queryable citation graph.

### Feature 1.1: Interest Model Implementation

**Overview**

Store, update, and track the user's evolving interest model over time. Calculate interest decay, rank emerging vs established interests, and find topic relationships.

**Scope & Boundaries**

- Maintain a directed graph: topic → strength, recency, frequency
- Update on every classified signal (aggregated at topic level)
- Decay: older signals worth less; strength → 0 over time (configurable half-life)
- Relationships: if two topics co-occur in signals, add edge with co-occurrence count
- Queries:
  - `get_interests(user, min_strength)` → sorted list
  - `get_interest_trajectory(topic, days)` → time series of strength
  - `get_related_interests(topic, depth)` → adjacent topics in graph
- Do **not** predict future interests (that's Meta Agent)
- Do **not** modify signals (Interest Agent only reads)

**Dependencies**

- ✅ `store/memory.py` (interest graph schema already exists)
- ✅ `store/graph.py` (knowledge graph schema exists)
- Signal aggregation from Phase 0.4

**High-Level Design Approach**

1. **Graph structure** (SQLite in `store/graph.py`):
   ```
   interest_nodes: id, topic, user, created, last_updated, strength, frequency, source_signal_ids
   interest_edges: topic1, topic2, user, co_occurrence_count, last_updated
   ```
2. **Strength calculation**:
   ```
   strength(t) = sum(confidence_i * exp(-decay * (now - timestamp_i)) for all signals with topic t)
   decay = ln(2) / half_life_hours  # default 720h = 30 days
   ```
3. **Update flow**:
   - Interest Agent runs on schedule (e.g., every 6 hours)
   - Query recent aggregated signals
   - For each (topic, confidence) pair, recompute strength
   - Detect new topics (strength > threshold and created recently)
   - Update edges: if topic A and B both in same window, increment co_occurrence
4. **Queries** expose trending, stable, and emerging interests

**Data Models & Schemas**

```python
# src/store/graph.py (extend)
class InterestGraph:
    # Nodes: topic, user, created, last_updated, strength (cached), frequency
    def add_or_update_topic(self, user: str, topic: str, confidence: float, timestamp: datetime) -> None:
        """Add/update a topic node with a new signal."""
    
    def decay_all(self, user: str, half_life_hours: float = 720) -> None:
        """Recompute strength for all topics; call after new signals arrive."""
    
    def get_interests(self, user: str, min_strength: float = 0.3, limit: int = 20) -> list[Interest]:
        """Return topics sorted by strength (descending)."""
    
    def get_trajectory(self, user: str, topic: str, days: int = 30) -> list[tuple[datetime, float]]:
        """Time series of strength for a topic."""
    
    def get_related(self, user: str, topic: str, depth: int = 1) -> list[tuple[str, int]]:
        """Related topics (co-occurring) and edge weights."""
    
    def get_new_interests(self, user: str, since_hours: int = 24) -> list[str]:
        """Topics that appeared in last N hours."""

@dataclass
class Interest:
    topic: str
    strength: float          # 0-1
    frequency: int           # how many signals
    trajectory: list[float]  # last 7 days
    related: list[str]       # top 3 related
```

**External API/Service Dependencies**

- None

**Implementation Complexity**

**Medium** — graph operations are straightforward, but decay math and trending detection require care.

**Estimated Effort**

- Graph schema + schema migration: 2 days
- Strength calculation & decay: 2 days
- Relationship detection: 1 day
- Query implementations: 1 day
- Tests (unit + integration): 2 days
- **Total: 8 days**

**Success Criteria**

1. After receiving 3 GitHub signals tagged "ML", interest in "ML" exists with strength ~0.9
2. After 30 days with no signals, strength decays to ~0.45 (half-life)
3. If "ML" and "NLP" both appear in same day's signals, co-occurrence edge is created
4. `get_interests()` returns topics ordered by strength, highest first
5. `get_trajectory()` plots strength over time correctly

**Potential Risks**

1. **Decay tuning**: Half-life chosen poorly; interests fade too fast or too slow. *Mitigation:* ship conservative (30-day half-life); iterate based on feedback.
2. **Co-occurrence noise**: Unrelated topics cluster because they appeared in one noisy signal. *Mitigation:* require 3+ co-occurrences before creating edge; use confidence threshold.
3. **Graph size**: Over months, hundreds of topics and edges. *Mitigation:* prune old, low-strength topics annually; keep recent 12 months full-res.

**Related Documentation**

- [Interest Graph Schema](docs/impl/03-vector-db-and-storage.md#interest-graph)
- [Memory Store](src/store/memory.py)

---

### Feature 1.2: Research Agent Trigger Logic

**Overview**

Define when and how the Research Agent is triggered. The Interest Agent detects new or strengthened interests and decides whether to trigger research.

**Scope & Boundaries**

- Detect new interests (created < 24 hours, strength > threshold)
- Detect strengthened interests (strength increased by >20% in last 24h)
- Apply rate limiting (don't research the same topic within 7 days unless strength >0.8)
- Apply cap (max 3 research triggers per day to respect OpenRouter rate limits)
- Emit `ResearchTopic(topic, strength, source_signal_id, depth)` command to Core Engine
- Pass topic, interest strength, and context (related topics) to Research Agent
- Do **not** perform the research itself (that's Research Agent's job)

**Dependencies**

- Interest model from Feature 1.1
- Core engine command submission (`engine.submit()`)
- Rate limiting tracking in memory store

**High-Level Design Approach**

1. **Trigger conditions**:
   ```
   if (topic.created_at < now - 24h) and (topic.strength > 0.5):
       trigger_research()
   elif (strength_delta(24h) > 0.2) and (now - topic.last_researched > 7d):
       trigger_research()
   ```
2. **Rate limiting**:
   - Track `research_runs` table: `(user, topic, triggered_at)`
   - Allow 3 concurrent research runs per user
   - If 3 active, queue the 4th for next slot
3. **Depth assignment**:
   - `strength < 0.4`: depth="light" (quick skim)
   - `strength 0.4–0.7`: depth="normal" (standard)
   - `strength > 0.7`: depth="deep" (chase citations)
4. **Cooldown tracking**:
   - `interest_research_cooldown` table: `(user, topic, last_triggered_at)`
   - Skip if `now - last_triggered < cooldown_days`, unless strength jumped

**Data Models & Schemas**

```python
# src/store/memory.py (extend)
class MemoryStore:
    # Table: research_runs (user, topic, triggered_at, status, depth)
    # Table: interest_research_cooldown (user, topic, last_triggered_at)
    
    async def trigger_research(self, user: str, topic: str, strength: float, 
                               source_signal_id: str) -> bool:
        """
        Check conditions; if met, submit ResearchTopic command.
        Return True if triggered, False if rate-limited.
        """
    
    async def get_active_research_count(self, user: str) -> int:
        """How many research runs are in flight for this user?"""
    
    async def mark_research_triggered(self, user: str, topic: str) -> None:
        """Update cooldown timestamp."""

# src/agents/interest.py
class InterestAgent:
    async def decide_triggers(self, user: str) -> list[ResearchTopic]:
        """
        Query strengthened/new interests; apply rate limits; return trigger list.
        This is the decision point: should we research this topic?
        """
```

**External API/Service Dependencies**

- None (all local decision-making)

**Implementation Complexity**

**Low** — straightforward decision logic and rate-limit tracking.

**Estimated Effort**

- Rate limiting tables + methods: 2 days
- Trigger logic (new + strengthened detection): 1 day
- Cooldown tracking: 1 day
- Tests (decision matrix, rate limit behavior): 2 days
- **Total: 6 days**

**Success Criteria**

1. A new interest with strength 0.6 triggers research immediately
2. An interest with strength 0.3 does not trigger research
3. Same topic does not trigger twice within 7 days unless strength > 0.8
4. When 3 research runs are active, the 4th is queued; released when one completes
5. Strength increase of 30% in 24 hours triggers research even if cooldown exists

**Potential Risks**

1. **Cascading triggers**: Noisy signals cause many false positives. *Mitigation:* use high confidence threshold (0.6+) for topic extraction.
2. **Research queue starvation**: If user has many interests, some never get researched. *Mitigation:* implement priority queue; prioritize high-strength and recently active interests.

**Related Documentation**

- [Interest Agent Design](docs/impl/05-meta-agent-and-skills.md#interest-agent)
- [Core Command Submission](src/core/engine.py)

---

### Feature 1.3: Knowledge Graph Integration

**Overview**

Store research findings in a knowledge graph. Build citation relationships, extract entity/concept relationships, and enable novelty detection.

**Scope & Boundaries**

- Two graph types: Citation Graph (papers, citations, PDFs) and Knowledge Graph (concepts, entities, relationships)
- Citation Graph: nodes are papers/articles; edges are citation relationships
- Knowledge Graph: nodes are concepts/entities; edges are "relates_to", "is_subtype_of", "contradicts", etc.
- Store novelty score per node (new papers are 1.0; older papers are lower)
- Query by topic: retrieve all concepts and papers related to a topic
- Enable subgraph extraction: "show me the knowledge graph for machine learning papers published in 2024"
- Do **not** modify graphs based on user feedback yet (Meta Agent does that)

**Dependencies**

- ✅ `store/graph.py` (schema exists)
- Research Agent (produces findings)
- Entity Relation Extraction skill (`skills/entity_relation.py`)
- Graph Construction skill (`skills/graph_construction.py`)

**High-Level Design Approach**

1. **Citation Graph**:
   - Nodes: paper (id, title, authors, venue, published_date, pdf_url, content_hash)
   - Edges: cites (from_paper, to_paper, context)
   - Novelty: `1 - min(1, (now - published_date) / 365 / 5)` (5-year decay)
2. **Knowledge Graph**:
   - Nodes: concept (id, label, description, inferred_type, first_seen, last_updated)
   - Edges: relation (concept1, concept2, relation_type, confidence, sources)
   - Relation types: mentions, contradicts, refines, applies_to, inspired_by
3. **Insertion flow**:
   - Research Agent finds papers/articles for a topic
   - Entity Relation skill extracts concepts and relationships
   - Graph Construction skill adds nodes/edges, deduplicating by content hash
4. **Queries**:
   - `get_papers_for_topic(topic)` → sorted by novelty
   - `get_concepts(topic)` → concept nodes and relationships
   - `get_subgraph(concept, depth=2)` → connected subgraph

**Data Models & Schemas**

```python
# src/store/graph.py
class CitationGraph:
    async def add_paper(self, title: str, authors: list[str], venue: str, 
                        published_date: date, url: str, content: str) -> str:
        """Add paper node; return paper_id."""
    
    async def add_citation(self, from_paper_id: str, to_paper_id: str, context: str = "") -> None:
        """Add citation edge with context."""
    
    async def get_papers_for_topic(self, topic: str, limit: int = 20) -> list[Paper]:
        """Papers related to topic, sorted by recency + novelty."""
    
    async def get_subgraph(self, paper_id: str, depth: int = 2) -> Subgraph:
        """Ego network: this paper + cited/citing papers up to depth."""

class KnowledgeGraph:
    async def add_concept(self, label: str, description: str, 
                         inferred_type: str, topics: list[str]) -> str:
        """Add concept node; return concept_id."""
    
    async def add_relation(self, concept1_id: str, concept2_id: str, 
                          rel_type: str, confidence: float, sources: list[str]) -> None:
        """Add relation edge."""
    
    async def get_concepts(self, topic: str, limit: int = 50) -> list[Concept]:
        """Concepts related to topic."""
    
    async def get_relations(self, concept_id: str, rel_type: str | None = None) -> list[Relation]:
        """All relations from a concept."""

@dataclass
class Paper:
    id: str
    title: str
    authors: list[str]
    venue: str
    published_date: date
    url: str
    novelty: float  # 0-1, time decay
    relevance: float  # 0-1, topic match

@dataclass
class Concept:
    id: str
    label: str
    description: str
    type: str  # "technique", "framework", "problem", "dataset", "metric"
    first_seen: datetime
    last_updated: datetime
    topics: list[str]  # which research topics mention this

@dataclass
class Relation:
    concept1: str
    concept2: str
    type: str  # mentions, contradicts, refines, applies_to
    confidence: float
    sources: list[str]  # papers that assert this relation
```

**External API/Service Dependencies**

- arXiv API (for papers — implemented in Research Agent)
- None on this feature itself; Research Agent feeds it

**Implementation Complexity**

**Medium** — graph operations, but schema is straightforward.

**Estimated Effort**

- Graph schema + migrations: 2 days
- Paper/Concept insertion logic: 2 days
- Relation extraction integration: 2 days
- Query implementations: 2 days
- Tests (deduplication, subgraph extraction): 2 days
- **Total: 10 days**

**Success Criteria**

1. A paper is added to Citation Graph with correct metadata
2. Two papers citing the same work have an edge between them
3. Concepts extracted from paper abstracts are added to Knowledge Graph
4. `get_papers_for_topic()` returns papers sorted by novelty (recent weighted higher)
5. `get_subgraph()` recursively retrieves papers citing and cited by a paper
6. Duplicate papers (by content hash) are not inserted twice

**Potential Risks**

1. **Graph explosion**: Thousands of papers and concepts. *Mitigation:* implement pagination; periodically archive old low-relevance nodes.
2. **Concept deduplication**: "Machine learning" vs "ML" are the same concept. *Mitigation:* use embedding similarity to detect near-duplicates; merge manually or via clustering.
3. **Relation confidence**: Extracted relations may be wrong. *Mitigation:* include confidence score; query with threshold; feedback loop (Meta Agent) improves extractors.

**Related Documentation**

- [Graph Store Design](docs/impl/03-vector-db-and-storage.md#graph-stores)
- [Entity Relation Extraction Skill](skills/entity_relation.py)
- [Graph Construction Skill](skills/graph_construction.py)

---

### Feature 1.4: Research Agent

**Overview**

Autonomous agent that investigates a topic when triggered by the Interest Agent. Searches papers, GitHub repos, articles, and news, building citation and knowledge graphs as it goes.

**Scope & Boundaries**

- Triggered by Interest Agent with topic and strength
- Orchestrates research across multiple sources (arXiv, GitHub, Medium, news APIs)
- Extracts entities and relationships from findings
- Decides depth (light/normal/deep) and when to stop chasing citations
- Builds citation and knowledge graphs as findings are discovered
- Emits progress events and final Result with top findings
- Does **not** synthesize recommendations (that's Opportunity Agent)
- Does **not** modify the interest model (read-only)

**Dependencies**

- Interest Agent trigger (Feature 1.2)
- Knowledge Graph (Feature 1.3)
- Research connectors:
  - arXiv connector (papers) — **to be implemented**
  - GitHub trending connector (repos) — **to be implemented**
  - Medium connector (articles) — **to be implemented**
  - News connector (news) — **optional, defer to Phase 2**
- Entity Relation Extraction skill
- Graph Construction skill
- Summarization skill (summarize findings)

**High-Level Design Approach**

1. **LangGraph subgraph**:
   ```
   START
     ↓
   [Search arXiv, GitHub, Medium]
     ↓
   [Extract entities/relations]
     ↓
   [Add to graphs]
     ↓
   [Summarize findings]
     ↓
   [Decide: chase citations or stop?]
     ↓
   [if depth_remaining > 0: recursive → arXiv citations; else: END]
   ```
2. **Search strategy**:
   - **arXiv**: query with topic, filter by date (recent first), limit to top-k by relevance
   - **GitHub**: search by keyword, filter by stars (trending), limit to top-k
   - **Medium**: search by tag, filter by claps (trending)
3. **Entity extraction**:
   - Each found paper/article → extract concepts, entities, relationships
   - Deduplicate against existing Knowledge Graph
4. **Depth control**:
   - `light`: 1 search pass, no citation chasing
   - `normal`: 1 search pass + 1 round of citations (top-k cited papers)
   - `deep`: 1 search + 2 rounds of citations (recursive)
5. **Emit findings**:
   - Top papers (by relevance)
   - Top concepts (by mention frequency)
   - Interesting relations (contradictions, new frameworks)

**Data Models & Schemas**

```python
# src/agents/research.py
class ResearchAgent:
    async def research(self, topic: str, strength: float, depth: str = "normal") -> dict:
        """
        Research a topic; return findings.
        
        Args:
            topic: what to research
            strength: user interest strength (influences search scope)
            depth: "light" | "normal" | "deep"
        
        Returns:
            {
                "topic": str,
                "papers": [Paper, ...],  # top-k by relevance
                "concepts": [Concept, ...],  # top-k by frequency
                "relations": [Relation, ...],  # interesting relations
                "summary": str,  # natural language summary of findings
                "novelty_score": float,  # how much is new to our graph
                "run_time_seconds": int,
            }
        """

# src/research/connectors/arxiv.py
class ArxivConnector(Connector):
    async def search(self, query: str, limit: int = 20) -> list[Paper]:
        """Search arXiv; return papers."""
    
    async def get_citations(self, paper_id: str, limit: int = 10) -> list[str]:
        """Get arXiv IDs of papers cited by this paper."""

# src/research/connectors/github.py
class GitHubTrendingConnector(Connector):
    async def search(self, query: str, limit: int = 10, min_stars: int = 100) -> list[Repo]:
        """Search GitHub by keyword; filter by stars; return trending repos."""

# src/research/connectors/medium.py
class MediumConnector(Connector):
    async def search(self, query: str, limit: int = 10) -> list[Article]:
        """Search Medium by tag/keyword; return articles."""
```

**External API/Service Dependencies**

- **arXiv API** (free, no auth): https://arxiv.org/help/api/
- **GitHub REST API** (with auth token): per-hour rate limit (60–5000 depending on auth)
- **Medium** (scraping; no official API): use unofficial library or implement scraper carefully
- **News API** (optional): https://newsapi.org/ (free tier with limits)

**Implementation Complexity**

**High** — multi-source orchestration, graph building, recursive depth decisions.

**Estimated Effort**

- arXiv connector: 3 days
- GitHub connector: 2 days
- Medium connector: 2 days
- Research Agent orchestration: 3 days
- Graph construction integration: 2 days
- Tests (stub API, graph building): 3 days
- **Total: 15 days**

**Success Criteria**

1. Given topic "transformers", Research Agent finds top-20 arXiv papers on transformers
2. Each paper's metadata (title, authors, date, URL) is stored correctly
3. Citation relationships are added to Citation Graph
4. Concepts (e.g., "attention mechanism") are extracted and added to Knowledge Graph
5. Depth="light" does 1 search pass; depth="deep" chases 2 rounds of citations
6. Final summary accurately describes the research findings
7. Novelty score reflects how much is new to the existing graph (0 = all known; 1 = all new)

**Potential Risks**

1. **API rate limits**: OpenRouter + GitHub + arXiv. *Mitigation:* implement queuing, cache results, respect retry-after headers.
2. **Noisy extraction**: Entity extraction from free-text abstracts can be wrong. *Mitigation:* include confidence scores; discard low-confidence extractions.
3. **Citation chasing infinite loop**: If papers keep citing each other. *Mitigation:* track visited papers; respect depth limit strictly.
4. **Medium scraping fragility**: Medium can change HTML. *Mitigation:* use unofficial library (e.g., `python-medium`) rather than home-grown scraper.

**Related Documentation**

- [Research Agent Design](docs/impl/06-research-agent.md)
- [Research Connectors](src/research/connectors/)

---

## Phase 2: Opportunity & Brainstorming

**Timeline:** Weeks 4–5 (2026-07-12 to 2026-07-25)

**Goal:** Implement the Opportunity Agent to synthesize ideas from research findings, and the Brainstorming Agent for interactive sessions with KB + web search.

### Feature 2.1: Opportunity Agent Synthesis

**Overview**

Read the interest model, research findings, and knowledge graphs; synthesize gap-filling recommendations, propose new projects/areas to explore, and rank by relevance and novelty.

**Scope & Boundaries**

- Input: interest model, recent research findings, knowledge graph
- Output: list of opportunities (ideas, projects, skills to learn)
- Rank by: relevance to user's interests, novelty (not already explored), feasibility
- Include reasoning: why this opportunity matters
- Do **not** make implementation decisions (that's the user)
- Do **not** modify stored state (read-only analysis)

**Dependencies**

- Interest model (Feature 1.1)
- Knowledge Graph (Feature 1.3)
- Research Agent findings (Feature 1.4)
- Gap Analysis skill (to be implemented)
- Concept Synthesis skill (to be implemented)
- Ranking skill (to be implemented)

**High-Level Design Approach**

1. **Gap analysis**:
   - User's interests: [ML, NLP, Systems]
   - Concepts in those domains: [transformers, LLMs, distributed training, …]
   - Unexplored neighbors: concepts adjacent in Knowledge Graph not yet in interest model
   - Example: user interested in ML + NLP, but not "prompt engineering" (adjacent concept) → opportunity
2. **Idea synthesis**:
   - Recent papers + user's interests → "what project would combine these?"
   - Example: papers on knowledge graphs + interest in NLP → "build a KG for domain X"
3. **Ranking**:
   - Relevance: how much do recent papers + interests support this?
   - Novelty: how far from user's current projects?
   - Feasibility: rough estimate (1-month, 3-month, 6-month projects)
   - Interestingness: novelty - feasibility (prefer novel + feasible)
4. **Emit opportunities**:
   - Top-10 ranked by interestingness score
   - Include: title, description, reasoning, required skills, estimated effort

**Data Models & Schemas**

```python
# src/agents/opportunity.py
@dataclass
class Opportunity:
    id: str  # uuid
    title: str
    description: str
    relevance_score: float  # 0-1, how related to interests
    novelty_score: float  # 0-1, how unexplored
    feasibility_score: float  # 0-1, 1 = easy, 0 = very hard
    interestingness: float  # novelty * (1 - feasibility); highest = best
    reasoning: str  # natural language: why this opportunity?
    required_skills: list[str]
    estimated_effort: str  # "1-month", "3-month", "6-month"
    sources: list[str]  # paper/concept IDs that inspired this
    created_at: datetime

class OpportunityAgent:
    async def synthesize(self, user: str) -> list[Opportunity]:
        """
        Analyze interests + research findings; return ranked opportunities.
        Called on-demand or on schedule (e.g., daily).
        """
    
    async def save_opportunity(self, user: str, opportunity: Opportunity) -> None:
        """User bookmarked an opportunity."""
    
    async def dismiss_opportunity(self, user: str, opportunity_id: str) -> None:
        """User dismissed an opportunity; don't resurface similar ones."""

# src/store/memory.py (extend)
class MemoryStore:
    # Table: opportunities (id, user, title, ..., created_at, dismissed=False, saved=False)
    # Queries: get_top_opportunities(), dismiss_opportunity(), etc.
```

**External API/Service Dependencies**

- None (all computation on stored data)

**Implementation Complexity**

**High** — gap analysis and ranking require careful heuristics.

**Estimated Effort**

- Gap Analysis skill: 2 days
- Concept Synthesis skill: 2 days
- Ranking logic: 2 days
- Opportunity Agent orchestration: 2 days
- Storage + save/dismiss: 1 day
- Tests (ranking correctness, edge cases): 2 days
- **Total: 11 days**

**Success Criteria**

1. Given interests [ML, NLP], Research Agent findings on LLMs, Knowledge Graph contains [transformers, prompting, alignment]
2. Opportunity Agent identifies "prompt engineering" as high-novelty, high-relevance opportunity
3. Opportunity is ranked higher than unrelated concepts (e.g., biology papers)
4. Reasoning explains why (e.g., "You're interested in NLP and LLMs; prompt engineering is the core applied skill")
5. Estimated effort is reasonable (not "1-month" for learning a concept, "6-month" for a research project)
6. User can dismiss an opportunity; similar ones don't resurface
7. User can save an opportunity; it appears in opportunities view

**Potential Risks**

1. **Overfitting to recent papers**: If user reads 3 papers on LLMs, all opportunities are LLM-related. *Mitigation:* weight by broader interest model, not just recent research.
2. **Feasibility estimation**: Very rough heuristic. *Mitigation:* expose to user; let them correct.
3. **Ranking explosion**: Too many concepts, too many possible opportunities. *Mitigation:* filter to top-20 concepts; rank top-100 opportunities; show top-10.

**Related Documentation**

- [Gap Analysis Skill](skills/gap_analysis.py)
- [Concept Synthesis Skill](skills/concept.py)
- [Ranking Skill](skills/ranking.py)

---

### Feature 2.2: Brainstorming Agent Session Management

**Overview**

Full-featured Brainstorming Agent for interactive multi-turn sessions. Supports KB queries, web search, and can invoke Research Agent for deep dives. Sessions persist across restarts.

**Scope & Boundaries**

- Multi-turn conversation with user (REPL on CLI, threads on Slack)
- Retrieve from KB (vector DB) for context
- Web search for current information
- Route to Research Agent if user asks for deep research on a topic
- Maintain session state: conversation history, context window, referenced sources
- Save/resume sessions: checkpoint after each turn
- Do **not** train on user inputs (no online learning)
- Do **not** modify graphs or interests (read-only)

**Dependencies**

- Vector DB (Feature 0, phase 0)
- Knowledge Graph (Feature 1.3)
- Web search tool (to be implemented)
- Research Agent (Feature 1.4)
- Retrieval skill (already implemented)
- Summarization skill (already implemented)
- Context window management (to be implemented)

**High-Level Design Approach**

1. **Session lifecycle**:
   ```
   CREATE session: user → /brainstorm → session_id, empty history
   TURN: user query → retrieve KB + web search → LLM response → save session
   END: explicit /done or timeout
   RESUME: session_id → load history + context → continue
   ```
2. **Context window**:
   - Maintain last N turns (e.g., 10 turns = ~4k tokens)
   - When new turn comes in, include full history in LLM prompt
   - Trim if context exceeds limit
3. **Retrieval**:
   - User query → hybrid search (dense + sparse) → top-5 chunks from KB
   - Include chunk citations
4. **Web search**:
   - For time-sensitive queries ("latest ML trends"), invoke web search
   - Heuristic: if KB chunks are old (>3 months), also web search
5. **Research Agent routing**:
   - User says "research this topic more deeply"
   - Brainstorming Agent submits `ResearchTopic` command, waits for completion
   - Retrieves new findings from Knowledge Graph, incorporates into response
6. **Checkpointing**:
   - After each turn, save session state to `brainstorm_sessions` table
   - Store: session_id, user, turn_count, history (JSON), context_tokens_used, created_at, updated_at

**Data Models & Schemas**

```python
# src/agents/brainstorm.py
@dataclass
class BrainstormSession:
    session_id: str
    user: str
    created_at: datetime
    updated_at: datetime
    turn_count: int
    history: list[Turn]  # [{role, text, citations}]
    context_tokens_used: int

@dataclass
class Turn:
    role: str  # "user" | "assistant"
    text: str
    citations: list[str]  # chunk IDs or source URLs
    timestamp: datetime

class BrainstormingAgent:
    async def create_session(self, user: str) -> str:
        """Create new session; return session_id."""
    
    async def add_turn(self, session_id: str, user_query: str) -> str:
        """
        Process user input; return assistant response.
        - Retrieve from KB
        - Web search if needed
        - Route to Research Agent if needed
        - Generate response
        - Save session
        - Return response text
        """
    
    async def resume_session(self, session_id: str) -> BrainstormSession:
        """Load session from disk; return history."""
    
    async def end_session(self, session_id: str) -> None:
        """Archive session."""

# src/store/memory.py (extend)
class MemoryStore:
    # Table: brainstorm_sessions (session_id, user, created_at, updated_at, turn_count, history_json)
    async def save_brainstorm_session(self, session: BrainstormSession) -> None:
        """Persist session state."""
    
    async def load_brainstorm_session(self, session_id: str) -> BrainstormSession:
        """Load session from disk."""
    
    async def list_brainstorm_sessions(self, user: str, limit: int = 10) -> list[BrainstormSession]:
        """Return user's recent sessions."""
```

**External API/Service Dependencies**

- Web search API (to be implemented; options: SerpAPI, DuckDuckGo, Brave)
- OpenRouter for Brainstorming Agent's LLM calls (already configured)

**Implementation Complexity**

**High** — multi-turn orchestration, context management, integration with other agents.

**Estimated Effort**

- Session persistence (storage): 2 days
- Context window management: 2 days
- Retrieval + citation tracking: 2 days
- Web search integration: 2 days
- Research Agent routing: 2 days
- LangGraph subgraph: 2 days
- Tests (multi-turn, context overflow, resume): 3 days
- **Total: 15 days**

**Success Criteria**

1. User creates session → session_id returned
2. User queries "what is a transformer?" → KB retrieval returns relevant chunks
3. User queries "latest LLM papers 2024" → web search is invoked; current info returned
4. User queries "research prompt engineering in depth" → Research Agent triggered; findings incorporated
5. 10-turn conversation fits in context window without truncation
6. Session is saved after each turn
7. Closing browser/Slack + returning hours later → session resumed with full history
8. Old sessions can be archived/deleted (garbage collection)

**Potential Risks**

1. **Context explosion**: Long sessions with many turns exceed token limit. *Mitigation:* implement sliding window; summarize old turns if needed.
2. **Web search latency**: Web search API is slow, user sees delay. *Mitigation:* run web search in parallel with KB retrieval.
3. **Research Agent blocking**: User waits for research to complete. *Mitigation:* make asynchronous; tell user "researching, I'll update you"
4. **Citation accuracy**: Chunk citations must be correct. *Mitigation:* store chunk_id → content hash mapping; verify on load.

**Related Documentation**

- [Brainstorming Feature](docs/personal-assistant.brainstorm-feature.md)
- [Session Management](src/agents/brainstorm.py)

---

## Phase 3: Advanced Features & Optimization

**Timeline:** Weeks 6–8+ (2026-07-26 onwards)

**Goal:** Complete system integration, continuous operation, and advanced features.

### Feature 3.1: Digest Generation

**Overview**

Daily synthesis of insights from all agents. Present top opportunities, interesting research, activity summary, and recommendations in CLI and Slack.

**Scope & Boundaries**

- Scheduled: daily at configurable time (e.g., 7:30 AM)
- Content: top opportunities, recent research findings, activity trends, recommended actions
- Format: natural language summary with citations and actionable items
- Channels: Slack #assistant channel + CLI `pa digest`
- Include: why each insight matters, sources
- Do **not** include raw data; synthesize into narrative

**Dependencies**

- Opportunity Agent (Feature 2.1)
- Research Agent (Feature 1.4)
- Interest model (Feature 1.1)
- Signal aggregation (Feature 0.4)
- Summarization skill

**High-Level Design Approach**

1. **Digest orchestration** (runs daily):
   - Fetch recent opportunities (top-5 not dismissed)
   - Fetch recent research findings (papers added in last 24h)
   - Fetch activity summary (signals from last 24h)
   - Fetch trending interests (strength increased in last 24h)
2. **Synthesis**:
   - Combine into narrative: "You were very active in X. Here's what you're learning: Y. Opportunities: Z."
   - Include metrics: activity level, research scope, interest strength deltas
3. **Format**:
   - **Slack**: Rich blocks (sections, bullets, links)
   - **CLI**: Formatted text with colors and tables
4. **Schedule**: Cron job (via APScheduler or similar)

**Data Models & Schemas**

```python
# src/agents/meta.py (digest subgraph)
@dataclass
class DigestItem:
    type: str  # "opportunity" | "research" | "trend" | "metric"
    title: str
    summary: str
    sources: list[str]
    relevance: float

class MetaAgent:
    async def generate_digest(self, user: str) -> Digest:
        """
        Synthesize insights from last 24 hours.
        Returns structured digest ready for rendering.
        """

# src/adapters/cli/app.py (digest command)
@app.command()
async def digest(
    date: Optional[str] = typer.Option(None, help="Date (YYYY-MM-DD) or 'today'")
) -> None:
    """Show daily digest of insights."""

# src/adapters/slack/app.py (digest event on schedule)
# Scheduled via APScheduler to post daily
```

**External API/Service Dependencies**

- OpenRouter (for synthesis LLM calls)

**Implementation Complexity**

**Medium** — gathering data and synthesis is straightforward; formatting is repetitive.

**Estimated Effort**

- Data gathering + synthesis: 2 days
- CLI formatting: 1 day
- Slack formatting (rich blocks): 1 day
- Scheduling (APScheduler): 1 day
- Tests (stub agents, format validation): 2 days
- **Total: 7 days**

**Success Criteria**

1. Digest is generated daily at configured time
2. Includes top 3 opportunities, top 3 research findings, activity summary
3. Slack digest is formatted nicely (sections, links, actionable)
4. CLI digest is readable (colors, tables)
5. User can request digest for a specific date via `pa digest --date 2026-06-20`
6. No sensitive data in digest (all public findings)

**Potential Risks**

1. **Empty digest**: If no recent activity, digest is boring. *Mitigation:* include interesting older items if recent items sparse.
2. **Too long**: Digest becomes a wall of text. *Mitigation:* strictly limit to top-N items; include link to full view.

**Related Documentation**

- [Meta Agent](docs/impl/05-meta-agent-and-skills.md#meta-agent)
- [CLI Digest Command](src/adapters/cli/app.py)

---

### Feature 3.2: Meta Agent Performance Review

**Overview**

Meta Agent analyzes feedback on recommendations. Scores agent performance (Research Agent accuracy, Opportunity Agent relevance, Brainstorming Agent helpfulness). Proposes prompt/skill improvements. All proposals are human-reviewed before applying (D6 gate).

**Scope & Boundaries**

- Input: feedback from users, usage metrics (engagement, relevance ratings)
- Output: performance scores and improvement proposals
- Proposals: prompt edits, skill weights, tool configurations
- Gate: every proposal requires explicit human approval
- Do **not** apply changes automatically (violates D6)
- Do **not** modify feedback data (audit log)

**Dependencies**

- Feedback tracking (users rate recommendations)
- Agent usage metrics (signals table with engagement)
- Proposals table (`proposals` in memory store)
- Prompt/skill templates

**High-Level Design Approach**

1. **Feedback collection**:
   - After each recommendation (opportunity, research finding), user rates:
     - Relevance (1-5)
     - Usefulness (1-5)
     - Accuracy (1-5, for research findings)
   - Store in `feedback` table with reference to recommendation
2. **Metrics computation**:
   - Per agent, compute: average relevance, usefulness, accuracy over last N recommendations
   - Track: how many recommendations resulted in user action (saved, acted upon)
3. **Performance review** (monthly or on-demand):
   - Compare current metrics to historical baseline
   - Identify: which skills/tools are underperforming?
   - Propose: edits to prompts, rank weights, tool selection logic
4. **Proposal workflow**:
   - Meta Agent generates proposal (e.g., "increase novelty_weight from 0.3 to 0.4 in Opportunity ranking")
   - Proposal stored as a diff + reasoning
   - User reviews via `pa proposals` command
   - User approves/rejects
   - If approved, apply to `settings.toml` or skill config (git commit, PR-like flow)

**Data Models & Schemas**

```python
# src/core/commands.py
@dataclass(frozen=True)
class Feedback(Command):
    """User rates a recommendation."""
    ref: str  # recommendation ID
    verdict: str  # "accept" | "reject" | "correct"
    rating: Optional[int]  # 1-5 for relevance/usefulness/accuracy
    notes: Optional[str]

# src/store/memory.py
class MemoryStore:
    # Table: feedback (id, user, ref, verdict, rating, notes, created_at)
    # Table: proposals (id, user, agent, proposal_text, reasoning, status, created_at, approved_at)
    # status: "pending" | "approved" | "rejected" | "applied"

@dataclass
class PerformanceMetrics:
    agent: str
    timeframe: str  # "last_7_days", "last_30_days", "all_time"
    recommendations_count: int
    avg_relevance: float
    avg_usefulness: float
    avg_accuracy: float
    action_rate: float  # % that led to user action
    trend: str  # "improving" | "stable" | "declining"

@dataclass
class Proposal:
    id: str
    agent: str
    proposal_text: str  # natural language: "Change prompt for Research Agent to..."
    reasoning: str  # why is this change good?
    diff: str  # git-like diff showing exact change
    status: str  # pending, approved, rejected, applied
    created_at: datetime

class MetaAgent:
    async def compute_metrics(self, user: str, agent: str, days: int = 30) -> PerformanceMetrics:
        """Analyze feedback; return performance metrics."""
    
    async def generate_proposal(self, user: str, agent: str) -> Proposal:
        """Based on metrics, propose an improvement."""
    
    async def list_proposals(self, user: str, status: str = "pending") -> list[Proposal]:
        """Pending proposals for review."""
    
    async def apply_proposal(self, user: str, proposal_id: str, approved: bool) -> None:
        """User approves/rejects a proposal."""
```

**External API/Service Dependencies**

- None

**Implementation Complexity**

**Medium** — metrics computation is straightforward; proposal generation requires careful reasoning.

**Estimated Effort**

- Feedback table + storage: 1 day
- Metrics computation: 2 days
- Proposal generation logic: 2 days
- CLI review interface (`pa proposals`): 1 day
- Apply proposal + git integration: 1 day
- Tests (feedback flow, metrics, proposal generation): 2 days
- **Total: 9 days**

**Success Criteria**

1. User rates a recommendation as "relevant=4, useful=5"
2. Metrics are computed: "Opportunity Agent relevance: 4.2/5 avg"
3. Meta Agent proposes: "Increase novelty weight in ranking"
4. Proposal includes diff showing exact config change
5. User can approve proposal via `pa proposals approve <id>`
6. Approved proposal is applied (config updated, git commit created)
7. Rejected proposals are logged; not re-proposed for 30 days

**Potential Risks**

1. **Proposal quality**: Meta Agent's proposals may be bad. *Mitigation:* human review gate (D6); test proposals on stub data before applying.
2. **Feedback sparsity**: If users don't rate, no metrics. *Mitigation:* make rating frictionless (emoji reactions on Slack, 1-click on CLI).
3. **Proposal drift**: Iterative small changes accumulate to large shifts. *Mitigation:* track proposal history; undo recent batches if performance degrades.

**Related Documentation**

- [D6: Self-Modification Gate](docs/personal-assistant.plans.md#foundational-decisions)
- [Meta Agent](docs/impl/05-meta-agent-and-skills.md#meta-agent)

---

### Feature 3.3: System Integration (Service Installation)

**Overview**

Install Personal Assistant as a system service for continuous operation on Windows, macOS, and Linux.

**Scope & Boundaries**

- **Windows**: Register as a service (via `nssm` or native Windows Service API)
- **macOS**: Install as LaunchAgent (plist in `~/Library/LaunchAgents/`)
- **Linux**: systemd service unit file
- Auto-start on boot
- Graceful shutdown on system halt
- Logging to system logs (Windows Event Log, macOS Console, journald)
- Config file: `~/.assistant/config/settings.toml`
- Data dir: `~/.assistant/data/`

**Dependencies**

- Core engine (all previous phases)
- Daemon framework (async loop, signal handling)

**High-Level Design Approach**

1. **Windows**:
   - Use `pywin32` to register service
   - Script: `src/service/windows_install.py`
   - Service runs `python -m src.daemon`
2. **macOS**:
   - Create plist template in `install/com.assistant.daemon.plist`
   - User runs: `install/macos_install.sh`
   - Installs plist to `~/Library/LaunchAgents/`
3. **Linux**:
   - Create systemd service template in `install/assistant-daemon.service`
   - User runs: `sudo install/linux_install.sh`
   - Installs service + enables + starts
4. **Graceful shutdown**:
   - Handle SIGTERM, SIGINT (Windows uses `SERVICE_CONTROL_STOP`)
   - Checkpoint active jobs
   - Close DB connections
   - Exit

**Data Models & Schemas**

```python
# src/daemon.py
class Daemon:
    async def start(self) -> None:
        """
        Main daemon loop.
        - Initialize services
        - Set up signal handlers
        - Run event loop
        - Graceful shutdown on signal
        """
    
    async def run_scheduled_jobs(self) -> None:
        """
        Event loop that runs:
        - Ingest (signal collection)
        - Interest update
        - Research triggers
        - Digest generation
        """

# install/windows_install.py
def install_windows_service() -> None:
    """Register daemon as Windows service."""

# install/macos_install.sh
#!/bin/bash
# Install LaunchAgent

# install/linux_install.sh
#!/bin/bash
# Install systemd service
```

**External API/Service Dependencies**

- None (all local)

**Implementation Complexity**

**Low** — straightforward service installation; platform-specific scripting.

**Estimated Effort**

- Windows service script: 1 day
- macOS LaunchAgent: 1 day
- Linux systemd: 1 day
- Graceful shutdown logic: 1 day
- Tests (stub service, signal handling): 1 day
- **Total: 5 days**

**Success Criteria**

1. On Windows: `python install/windows_install.py` installs service; service starts automatically on boot
2. On macOS: `bash install/macos_install.sh` installs LaunchAgent; agent runs on login
3. On Linux: `sudo bash install/linux_install.sh` installs systemd service; runs on boot
4. Sending SIGTERM to daemon gracefully shuts down (no data loss)
5. Daemon logs appear in system logs (Event Log on Windows, Console on macOS, journald on Linux)

**Potential Risks**

1. **Platform differences**: Service management is OS-specific. *Mitigation:* test on each platform; document assumptions.
2. **Permissions**: Daemon needs file access to `~/.assistant/`. *Mitigation:* ensure install script sets correct permissions.
3. **Updating daemon**: Stopping/restarting during operation. *Mitigation:* implement zero-downtime restart (background worker takes over from old process).

**Related Documentation**

- [Daemon Setup](docs/DAEMON_SETUP.md)

---

### Feature 3.4: State Persistence & Crash Recovery

**Overview**

Save/restore daemon state so it can recover from crashes without losing progress. Checkpoint agent runs, brainstorm sessions, and in-flight research.

**Scope & Boundaries**

- Checkpoint agent states (LangGraph state snapshots)
- Save brainstorm session history
- Mark in-flight jobs as interrupted (for recovery)
- On daemon restart: recover interrupted jobs
- Do **not** replay user input (user decides to retry)
- Do **not** corrupt data on crash (use transactions)

**Dependencies**

- All previous phases

**High-Level Design Approach**

1. **LangGraph checkpointing** (built-in):
   - LangGraph saves state after each node
   - On crash, resume from last checkpoint
   - No additional work needed if using LangGraph properly
2. **In-flight job tracking**:
   - `jobs` table: `(job_id, user, command, status, started_at, last_checkpoint_at, state_json)`
   - After each step, update `last_checkpoint_at` and `state_json`
   - On restart: query jobs with `status='running'` and `last_checkpoint_at < restart_time`
   - Mark as `interrupted`; emit event to user
4. **Brainstorm session recovery**:
   - Already checkpointing after each turn (Feature 2.2)
   - On restart: load latest session state
5. **Vector/Graph DB recovery**:
   - Qdrant and SQLite both support transactions
   - Ensure all writes are transactional (automatic for Qdrant, configure for SQLite)

**Data Models & Schemas**

```python
# src/core/jobs.py (extend)
@dataclass
class Job:
    job_id: str
    user: str
    command: Command
    status: str  # "queued" | "running" | "interrupted" | "complete" | "failed"
    started_at: datetime
    last_checkpoint_at: datetime
    checkpoint_state: dict  # JSON-serializable LangGraph state
    result: Optional[dict]
    error: Optional[str]

class JobQueue:
    async def recover_interrupted_jobs(self) -> list[str]:
        """On daemon restart, find interrupted jobs and emit recovery event."""
    
    async def save_checkpoint(self, job_id: str, state: dict) -> None:
        """Periodically save state during job execution."""

# src/core/events.py (extend)
@dataclass(frozen=True)
class Interrupted(Event):
    """Job was interrupted; resuming from checkpoint."""
    phase: str
    context: dict
```

**External API/Service Dependencies**

- None

**Implementation Complexity**

**Low** — LangGraph handles most of it; just ensure checkpoint logic is correct.

**Estimated Effort**

- Job checkpoint table + methods: 1 day
- LangGraph checkpoint configuration: 1 day
- Recovery logic on daemon start: 1 day
- Tests (crash simulation, checkpoint recovery): 2 days
- **Total: 5 days**

**Success Criteria**

1. Long-running Research Agent job crashes halfway through
2. On restart, job is marked `interrupted`
3. User can retry job from last checkpoint (e.g., already searched arXiv, need to search GitHub)
4. No data loss (partial results are saved)
5. Brainstorm session survives daemon restart

**Potential Risks**

1. **State corruption**: If checkpoint state is invalid JSON. *Mitigation:* validate on save; test deserialization.
2. **Stale checkpoints**: If state evolves but checkpoint doesn't. *Mitigation:* checkpoint frequently (after each agent action); use atomic writes.

**Related Documentation**

- [Job Queue & State Management](src/core/jobs.py)
- [LangGraph Persistence](https://langchain-ai.github.io/langgraph/concepts/persistence/)

---

### Feature 3.5: Browser Connector (Optional)

**Overview**

Monitor browser activity: visited URLs, time spent, open tabs. Infer research activity and interest triggers.

**Scope & Boundaries**

- Track URLs visited (via extension or local HTTP proxy)
- Track time spent per domain (rough estimate from open tabs)
- Infer activity: research (academic sites), news (RSS feeds), shopping, etc.
- Emit signals on domain switches (e.g., spent hour on arXiv, now on GitHub)
- Do **not** log full page contents (privacy)
- Require explicit user consent (privacy policy + local-only storage)

**Dependencies**

- Browser extension (Chrome/Firefox) OR local HTTP proxy
- Signal pipeline (Phase 0)

**High-Level Design Approach**

1. **Browser extension approach** (preferred, privacy-respecting):
   - User installs extension
   - Extension monitors active tab URL (built-in browser APIs)
   - On tab switch or time interval, emit event to local HTTP server
   - Local server stores in `ingest_browser` table
   - Privacy: URLs stay local, never sent to OpenRouter
2. **HTTP proxy approach** (simpler, less privacy):
   - User configures proxy in OS network settings
   - Proxy logs URLs, forwards requests
   - Simpler but captures all network traffic

*Recommendation: Start with extension (harder but privacy-respecting). Defer proxy to Phase 3+ if needed.*

**Data Models & Schemas**

```python
# src/ingest/connectors/browser.py
@dataclass
class BrowserActivity:
    url: str
    domain: str
    title: str
    timestamp: datetime
    time_spent_seconds: int

class BrowserConnector(Connector):
    async def fetch(self) -> list[ActivitySignal]:
        """
        Poll browser activity log.
        Return signals for domain switches.
        """
```

**External API/Service Dependencies**

- None (all local)

**Implementation Complexity**

**High** — browser extension development is new domain; HTTP proxy is simpler but less private.

**Estimated Effort**

- Browser extension (Chrome/Firefox): 5–7 days
- OR HTTP proxy: 3 days
- Connector integration: 1 day
- Privacy policy + consent: 1 day
- **Total: 6–8 days (extension) or 4 days (proxy)**

**Success Criteria**

1. Extension detects tab switch to arXiv → signal emitted
2. Time spent per domain is tracked accurately
3. URL is not logged to any external service
4. User consent is recorded (privacy policy accepted)
5. Extension works on Chrome, Firefox, Safari

**Potential Risks**

1. **Extension maintenance**: Chrome/Firefox API changes. *Mitigation:* minimize extension code; use well-maintained libraries.
2. **Privacy concerns**: Users worried about tracking. *Mitigation:* make architecture transparent (local-only storage); clear privacy policy; allow disabling.
3. **Browser API limits**: Different browsers have different APIs. *Mitigation:* start with Chromium (Chrome/Edge); Firefox later.

**Related Documentation**

- [Ingest Pipeline](docs/impl/04-daily-research-agent.md)

---

### Feature 3.6: Monitoring & Observability

**Overview**

Metrics for signal throughput, agent performance, error rates, and system resource usage. Optional: visualization dashboard.

**Scope & Boundaries**

- Metrics: signals/hour, KB query latency, agent completion time, error count/type
- Logs: structured JSON logs (signal, agent, error)
- Dashboards (optional): view metrics over time, spot trends
- Retention: metrics for last 90 days, keep detailed logs for 7 days
- Do **not** send metrics to external service (privacy); store locally

**Dependencies**

- All previous phases

**High-Level Design Approach**

1. **Metrics collection**:
   - Instrument core components (ingest, agents, retrieval)
   - Use library like `prometheus_client` (Python)
   - Expose metrics endpoint (optional, for dashboards)
2. **Structured logging**:
   - All log lines are JSON (timestamp, level, component, message, context)
   - Write to `~/.assistant/logs/` with rotation
3. **Queries**:
   - `pa metrics` → display daily metrics (signal count, agent runs, errors)
   - `pa logs` → tail recent logs
   - Optional dashboard: `localhost:8080/dashboard`

**Data Models & Schemas**

```python
# src/metrics.py
class MetricsCollector:
    def record_signal(self, source: str, topic: str, confidence: float) -> None:
        """Track ingest metric."""
    
    def record_agent_run(self, agent: str, duration_seconds: float, success: bool) -> None:
        """Track agent execution."""
    
    def record_retrieval(self, query: str, latency_ms: float) -> None:
        """Track KB retrieval latency."""
    
    def get_daily_metrics(self, days: int = 7) -> dict:
        """Return aggregated metrics."""

# src/adapters/cli/app.py
@app.command()
async def metrics(days: int = typer.Option(7)) -> None:
    """Show system metrics."""

# Optional: src/adapters/web/dashboard.py
# Simple web dashboard showing metrics graphs
```

**External API/Service Dependencies**

- None (all local)

**Implementation Complexity**

**Low** — straightforward metric collection; dashboard is optional.

**Estimated Effort**

- Metrics instrumentation: 2 days
- Structured logging: 1 day
- `pa metrics` command: 1 day
- Dashboard (optional): 3 days
- **Total: 4 days (without dashboard) or 7 days (with dashboard)**

**Success Criteria**

1. `pa metrics` shows signals/hour, agent runs/day, error count
2. Metrics are accurate (match actual data)
3. Logs are structured JSON and searchable
4. Metrics retention: last 90 days available
5. Optional dashboard displays charts

**Potential Risks**

1. **Overhead**: Metrics collection slows down system. *Mitigation:* batch collection; async I/O.
2. **Disk space**: Logs fill disk. *Mitigation:* implement rotation (e.g., 10MB per file, keep 7 days).

**Related Documentation**

- [Observability](docs/LOGGING_IMPLEMENTATION.md)

---

### Feature 3.7: Documentation & Developer Guide

**Overview**

Architecture diagrams, connector development guide, agent customization guide, troubleshooting runbooks, and API reference.

**Scope & Boundaries**

- Architecture diagrams (signals, agents, storage)
- How to write a custom connector
- How to add a new skill
- How to customize agent prompts
- Troubleshooting guide (common errors, how to debug)
- API reference (all commands, events, tools)
- Deployment guide (Windows/macOS/Linux service setup)

**Dependencies**

- None (documentation only)

**High-Level Design Approach**

Create docs under `docs/`:
- `architecture-diagrams.md` — mermaid diagrams
- `connectors-guide.md` — template + walkthrough
- `skills-guide.md` — template + examples
- `troubleshooting.md` — common issues
- `api-reference.md` — all commands/events/models
- `deployment.md` — service setup for each OS

**Data Models & Schemas**

None (documentation).

**External API/Service Dependencies**

None.

**Implementation Complexity**

**Low** — writing, not coding.

**Estimated Effort**

- Architecture diagrams: 1 day
- Connector guide + example: 1 day
- Skills guide: 1 day
- Troubleshooting: 1 day
- API reference: 2 days
- Deployment guide: 1 day
- **Total: 7 days**

**Success Criteria**

1. Developer can write a custom connector by following the guide
2. Developer can add a new skill by following the guide
3. Troubleshooting guide helps resolve common issues
4. API reference documents all public commands and events

**Related Documentation**

- [Agent Architecture Guide](docs/agent.architecture-guide.md)
- [Implementation Roadmap](docs/personal-assistant.implementation.md)

---

## Cross-Cutting Concerns

### Privacy & Data Handling

1. **Local-first**: All sensitive data (interests, conversations) stays on user's machine
2. **Selective filtering**: Before any OpenRouter API call, filter sensitive data (full file paths, email addresses)
3. **Connectors are opt-in**: User must explicitly enable Browser/Slack/calendar connectors
4. **Retention policy**: Define how long activity signals are kept (e.g., 12 months); implement auto-deletion
5. **User consent**: Browser/Slack connectors require explicit privacy policy acceptance

### Concurrency & Rate Limiting

1. **OpenRouter free tier**: 60 req/min, 1000 req/day limit
   - Implement queuing in `llm/openrouter.py`
   - Max 3 concurrent requests
   - Exponential backoff on rate limit errors
2. **GitHub API**: 60 req/hour (unauthenticated) or 5000/hour (with token)
   - Use authenticated requests
   - Respect `X-RateLimit-Remaining` header
3. **Avoid burst requests**: Schedule recurring jobs with jitter (not all at once)

### Idempotency & Deduplication

1. **Signals**: Group by content hash; don't store duplicate signals
2. **KB chunks**: Deduplicate by content hash before upserting to vector DB
3. **Graph nodes**: Deduplicate papers by arXiv ID; concepts by string similarity
4. **Operations**: Design all operations to be safe if retried (e.g., upserting opportunity should be idempotent)

### Observability & Debugging

1. **Structured logging**: All logs are JSON; include context (job_id, agent, step)
2. **Run replay**: Store full job state after each checkpoint; allow replaying runs
3. **User-facing status**: `pa status <job_id>` shows progress, logs, current step
4. **Error tracking**: Errors are logged with full context and suggestions (e.g., "rate limit hit, will retry at 14:30")

### Testing Strategy

1. **Unit tests**: Skills (pure functions) and storage operations
2. **Integration tests**: Signal flow end-to-end; Interest Agent triggering Research
3. **Stubbed agent tests**: Replace OpenRouter with stub LLM (return fixed responses)
4. **End-to-end**: Full system test with real services (run on CI with rate limit guards)

---

## Success Criteria

### Phase 0 Success (Week 1)
- [ ] GitHub connector emits signals
- [ ] Signals are classified into topics
- [ ] One complete signal flow (GitHub commit → topic → stored signal) works end-to-end
- [ ] `pa ask` returns a cited answer from KB

### Phase 1 Success (Weeks 2–3)
- [ ] Interest model is built and updated on schedule
- [ ] Interest Agent detects new/strengthened interests
- [ ] Research Agent is triggered and completes a run
- [ ] Citation Graph and Knowledge Graph are populated
- [ ] `pa research <topic>` works manually; returns findings with citations

### Phase 2 Success (Weeks 4–5)
- [ ] Opportunity Agent generates ranked opportunities
- [ ] Brainstorming Agent supports multi-turn sessions
- [ ] User can brainstorm with KB + web search
- [ ] Sessions persist across restarts
- [ ] `pa brainstorm` REPL and Slack integration work

### Phase 3 Success (Weeks 6–8+)
- [ ] Daemon runs continuously (Windows service, macOS LaunchAgent, Linux systemd)
- [ ] Daily digest is generated and delivered to Slack + CLI
- [ ] Meta Agent collects feedback and proposes improvements
- [ ] System survives crashes and recovers state
- [ ] Metrics and observability work; user can inspect system health
- [ ] Documentation is complete; developer can extend the system

---

## Risk Register

| Risk | Impact | Probability | Mitigation | Owner |
|------|--------|-------------|-----------|-------|
| **OpenRouter API changes** | Agents cannot run | Low | Pin API version; subscribe to breaking-change alerts | Dev |
| **Local model performance** | Agents are slow/inaccurate | Medium | Use OpenRouter (fallback to local if needed) | Dev |
| **LangGraph complexity** | Graphs become hard to debug | Medium | Unit-test each node; use LangGraph Studio for inspection | Dev |
| **Signal noise** | Interest model becomes noisy | Medium | High topic-extraction threshold; user feedback loop | Dev |
| **DB corruption on crash** | Data loss | Low | Use transactions; checkpoint frequently | Dev |
| **Rate limit hitting** | Research halts unexpectedly | Medium | Respect OpenRouter limits; queue requests | Dev |
| **Context window overflow** | Brainstorm sessions truncate | Low | Implement sliding window; summarize old turns | Dev |
| **Browser extension fragility** | Extension breaks on Chrome update | Medium | Use stable APIs; minimal extension code | Dev |
| **Privacy concerns** | User distrust | Medium | Document privacy clearly; local-only design; no telemetry | Dev |
| **Scope creep** | Project never completes | High | Strict phase gates; cut Phase 3 features if needed | Dev |

---

## Timeline Summary

```
Week 1 (Phase 0): Core signal flow
  ├─ Signals & aggregation (Features 0.1-0.4)
  └─ Exit: GitHub → topic → stored signal works

Week 2-3 (Phase 1): Interest & Research
  ├─ Interest model (Feature 1.1)
  ├─ Research trigger logic (Feature 1.2)
  ├─ Knowledge graphs (Feature 1.3)
  ├─ Research Agent (Feature 1.4)
  └─ Exit: Interest triggers research; graphs populated

Week 4-5 (Phase 2): Opportunity & Brainstorm
  ├─ Opportunity synthesis (Feature 2.1)
  ├─ Brainstorming Agent (Feature 2.2)
  └─ Exit: Brainstorm loop works end-to-end

Week 6-8+ (Phase 3): Advanced
  ├─ Digest generation (Feature 3.1)
  ├─ Meta Agent review (Feature 3.2)
  ├─ System integration (Feature 3.3)
  ├─ State persistence (Feature 3.4)
  ├─ Browser connector (Feature 3.5, optional)
  ├─ Observability (Feature 3.6)
  └─ Documentation (Feature 3.7)

Estimated Total: 8–12 weeks (solo dev, full engagement)
```

---

## Document Versioning

**Version:** 1.0.0  
**Status:** Draft  
**Last Updated:** 2026-06-21

Future iterations should update the `updated` field and changelog as features are completed or scope changes.

