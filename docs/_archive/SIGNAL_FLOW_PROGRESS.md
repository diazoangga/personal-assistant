# Signal Flow Implementation Progress

## Status: 100% Complete (5 of 5 Tasks Done)

### ✅ DONE

#### Task 1: Define Interest Signal Data Models
**File:** `src/core/signals.py` (NEW - 105 lines)

Classes created:
- `InterestSignal` - A classified signal with topics and confidences
- `InterestClassification` - Result of classifying a signal (carries the original signal's `timestamp`, not classification time)
- `StrengthSnapshot` - Snapshot of interest strength over time
- `StrengthChange` - Detected change in interest strength

Key methods:
- `InterestSignal.top_topic()` - Get highest confidence topic
- `StrengthChange.should_trigger_research()` - Check if change meets threshold

#### Task 2: Extend Interest Graph Storage
**File:** `src/store/memory.py` (MODIFIED)

New tables:
- `interest_signal_evidence` (signal_id, topic, confidence, timestamp) - every classified signal, used to recompute strength from scratch
- `interest_research_log` (topic, last_researched_at) - cooldown tracking, decoupled from `interest_nodes.last_active`

Methods added to `UserMemory` class:
1. `add_classified_signal()` - Store a classified signal in `interest_signal_evidence` + upsert `interest_nodes`
2. `get_strength()` - Sum exponentially-decayed confidence across all evidence rows for a topic, clipped to [0,1]
3. `get_strengthened_topics()` - Find topics with recent strength increase
4. `mark_researched()` / `should_research()` - Cooldown tracking via `interest_research_log`

Strength calculation:
```
strength = clip(sum(confidence_i * exp(-age_hours_i / decay_hours)), 0, 1)
Recent signals weighted higher; older signals decay exponentially
Decay window: 30 days (720 hours) by default
```

#### Task 3: Create Interest Agent
**File:** `src/agents/interest.py` (NEW - 240 lines)

Class: `InterestAgent`

Main flow:
```
1. process_signals(signals) → list[ActivitySignal] in
2. _classify_signals() → list[InterestClassification] (via LLM)
3. add_classified_signal() → store in interest graph (using original signal timestamp)
4. get_strength() → compute with decay
5. _detect_research_triggers() → list[ResearchTopic]
```

Key methods:
- `process_signals()` - Main orchestrator (receives signals, returns research topics)
- `_classify_signals()` - Use LLM to extract topics and confidences
- `_detect_research_triggers()` - Identify topics ready for research (cooldown check, then strength > 0.3)
- `_signal_to_text()` - Convert ActivitySignal to LLM-friendly text

LLM interaction:
```
Uses self.llm.complete(role="reasoning", prompt=...) with a JSON extraction prompt
Input: Activity signal description
Output: {topics: [...], confidences: [...], explanation: "..."}
```

#### Task 4: Wire into Daemon Loop
**Files:** `src/main_engine.py`, `src/daemon/service.py`, `src/daemon/__init__.py` (MODIFIED)

- `PersonalAssistantEngine.initialize()` now constructs `self._interest_agent = InterestAgent(engine=self._engine, llm=self._llm, memory=self._memory)` after the core `Engine` is built.
- Added `PersonalAssistantEngine.process_activity_signals(signals, user_id)` - thin wrapper around `InterestAgent.process_signals()`.
- Added `PersonalAssistantEngine.submit(cmd)` - thin wrapper around `Engine.submit()`.
- `PersonalAssistantDaemon._run_ingest_cycle()` now calls `self.engine.process_activity_signals(all_signals)` and submits each returned `ResearchTopic` via `self.engine.submit(topic)`, logging the job id.
- **Bug fixed along the way:** `src/daemon/__init__.py` eagerly re-exported `PersonalAssistantDaemon` from `.service`, which created a circular import once `main_engine.py` started importing `InterestAgent` (`main_engine → agents.interest → daemon.connector_base → daemon/__init__ → daemon.service → main_engine`). Nothing actually depended on the package-level re-export (`manager.py` already imported from `.service` directly), so it was removed.

Verified manually end-to-end (fake LLM, in-memory DB): a fake GitHub commit signal → classified → strength computed → `ResearchTopic(topic='rust', depth='deep')` → submitted to engine → job id returned.

#### Task 5: Integration Tests
**File:** `tests/test_signal_flow.py` (NEW - 12 tests, all passing)

Test classes:
1. `TestSignalToInterest` - classification + storage of a single signal
2. `TestResearchTriggers` - weak vs. strong signals, cooldown, deep-vs-normal depth
3. `TestStrengthDecay` - recent signals dominate; fully decayed signals contribute negligibly
4. `TestEndToEndSignalFlow` - multiple topics tracked independently; empty batch is a no-op
5. `TestDaemonIngestWiring` - `_run_ingest_cycle()` fetches from connectors, calls the engine, and submits returned `ResearchTopic` commands; no-signal and no-engine paths are safe no-ops

Run with: `poetry run python -m pytest tests/test_signal_flow.py -v`
(Plain `python -m pytest` fails in this environment - `pytest-asyncio`/`pytest-cov` are declared in `pyproject.toml` but only installed inside the Poetry-managed `.venv`. Always use `poetry run python -m pytest ...`.)

**3 real bugs were found and fixed while writing these tests, before any test was run:**
1. Cooldown always blocked research - `add_classified_signal()` and the old `should_research()` both touched/read `interest_nodes.last_active`, so the cooldown check always saw a just-updated timestamp. Fixed by introducing the separate `interest_research_log` table.
2. Strength never accumulated across multiple signals - `get_strength()` used to read a single cached value that was only set once. Fixed by summing decayed confidence across all `interest_signal_evidence` rows.
3. Wrong timestamp used for decay - signals were stored with `datetime.utcnow()` instead of the original `signal.timestamp`, making decay untestable (and wrong). Fixed by propagating `signal.timestamp` through `InterestClassification.timestamp`.

---

## Architecture Diagram

```
┌──────────────────────────┐
│   Data Connectors        │
│ (GitHub, Browser, Slack) │
└────────────┬─────────────┘
             │ ActivitySignal[]
             ↓
┌──────────────────────────────────────┐
│      Daemon Ingest Cycle             │
│  (runs every 15 minutes)             │
└────────────┬─────────────────────────┘
             │ signals
             ↓
┌──────────────────────────────────────┐
│       Interest Agent                 │
│  1. Classify via LLM                 │
│  2. Store in Interest Graph          │
│  3. Calculate Strength (decay)       │
│  4. Detect Strengthened Topics       │
│  5. Emit ResearchTopic commands      │
└────────────┬─────────────────────────┘
             │ ResearchTopic[]
             ↓
┌──────────────────────────┐
│ PersonalAssistantEngine  │
│      .submit()           │
│   → Engine.submit()      │
│   → Research Agent       │
│   (not yet implemented)  │
└──────────────────────────┘
```

---

## Key Design Decisions

1. **Exponential Decay for Strength**: Recent signals matter more than old ones
   - Formula: `strength * exp(-age_hours / 720)`
   - Default window: 30 days
   - Prevents stale interests from triggering research

2. **LLM Classification**: Use the configured LLM to extract topics
   - Prompt: JSON extraction of topics + confidences
   - Temperature: 0.3 (more deterministic)
   - Handles varied signal types (GitHub, Browser, Slack)

3. **Cooldown to Prevent Duplicate Triggers**: 24-hour window
   - Same topic won't trigger research more than once per day
   - Configurable via `should_research(cooldown_hours)`

4. **Research Threshold**: Strength > 0.3
   - Avoids research on weak signals
   - Depth scaling: "normal" if strength < 0.7, "deep" if ≥ 0.7

---

## Code Statistics

| File | Status |
|------|--------|
| `src/core/signals.py` | NEW ✅ |
| `src/store/memory.py` | MODIFIED ✅ |
| `src/agents/interest.py` | NEW ✅ |
| `tests/test_signal_flow.py` | NEW ✅ (12 tests passing) |
| `src/main_engine.py` | MODIFIED ✅ |
| `src/daemon/service.py` | MODIFIED ✅ |
| `src/daemon/__init__.py` | MODIFIED ✅ (circular-import fix) |

---

## Manual Verification (Next, Optional)

- Start daemon: `pa daemon start`
- Watch logs: `pa daemon logs -f`
- Look for: signal classification, interest updates, "Research trigger submitted" log lines

---

## Testing Checklist

- [x] GitHub signal → classified as topic
- [x] Topic strength stored in interest graph
- [x] Exponential decay works (older signals matter less)
- [x] Topic triggers research when strength > 0.3
- [x] Cooldown prevents duplicate research triggers within 24h
- [x] Daemon ingest cycle wires connector signals → Interest Agent → submitted ResearchTopic commands
- [x] All integration tests pass (12/12, via `poetry run python -m pytest tests/test_signal_flow.py -v`)
- [ ] LLM classification manually verified against a real OpenRouter call (only tested against a FakeLLM so far)

---

## Remaining Work Summary

**Current:** Signal Flow (Phase 0) is fully implemented, wired, and tested.
**Next:** Research Agent implementation - `ResearchTopic` commands are now submitted to `Engine.submit()`, but `Engine._handle_research()` requires `self._agents["research"]`, which doesn't exist yet. Submitted research triggers currently fail gracefully (logged as a failed Result event) until the Research Agent is built.
**Blocker:** None for Signal Flow itself; Research Agent is the next dependency to unblock the rest of the pipeline.
