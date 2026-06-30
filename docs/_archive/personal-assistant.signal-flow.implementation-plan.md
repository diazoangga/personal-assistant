# Signal Flow Implementation Plan

## Overview
Transform raw `ActivitySignal` objects from connectors into classified, stored interests that trigger the Research Agent.

**Goal:** One complete signal flow: GitHub commit → classified as topic → stored in interest model → triggers Research Agent if interest strengthened.

**Effort:** 5-7 days (Phase 0.1 from comprehensive plan)
**Status:** Ready to execute

---

## Architecture

```
Connector (GitHub, Browser, Slack)
    ↓ ActivitySignal
    ↓ (source, event_type, timestamp, data)
    ↓
┌─────────────────────────────────┐
│  Signal Processing Pipeline     │
├─────────────────────────────────┤
│ 1. Receive signals (hourly)     │
│ 2. Extract topics via LLM       │
│ 3. Compute confidence (0-1)     │
│ 4. Store in interest graph      │
│ 5. Calculate interest strength  │
│ 6. Detect if strengthened       │
│ 7. Trigger Research Agent       │
└────────────┬────────────────────┘
             ↓
        Interest Model (SQLite)
             ↓
        Research Agent triggered
```

---

## Implementation Tasks

### Task 1: Define Interest Signal Data Model (1 day)

**Files to create/modify:**
- `src/core/signals.py` (NEW) - Define `InterestSignal` and `InterestClassification`

**Code structure:**
```python
@dataclass
class InterestSignal:
    """A signal classified into interests."""
    activity_signal_id: str       # points back to original signal
    topics: list[str]             # ["machine learning", "python"]
    confidences: list[float]      # [0.8, 0.6] matching topics
    source: str                   # "github", "browser", etc.
    timestamp: datetime
    user_id: str
    
    def top_topic(self) -> tuple[str, float]:
        """Return highest confidence topic."""
        if not self.topics:
            return None, 0.0
        idx = self.confidences.index(max(self.confidences))
        return self.topics[idx], self.confidences[idx]

@dataclass
class InterestClassification:
    """Result of classifying a signal."""
    signal_id: str
    topics: list[str]
    confidences: list[float]
    explanation: str              # why we classified it this way
    model_version: str            # for tracking model changes
```

**Success criteria:**
- Data classes defined and importable
- Tests verify round-trip serialization
- Fields match Interest Agent input needs

---

### Task 2: Extend Interest Graph Storage (1 day)

**Files to modify:**
- `src/store/memory.py` - Add methods to `InterestGraph` class

**Methods to add:**
```python
class InterestGraph:
    def add_classified_signal(
        self, 
        user: str, 
        signal_id: str,
        topics: list[str],
        confidences: list[float],
        timestamp: datetime
    ) -> None:
        """Store a classified signal in the interest timeline."""
        # For each (topic, confidence) pair:
        # - Create/update node in interest_nodes table
        # - Add signal_id as evidence
        # - Update timestamp
    
    def get_strength(
        self, 
        user: str, 
        topic: str,
        decay_hours: int = 720  # 30 days
    ) -> float:
        """
        Compute interest strength using exponential decay.
        
        strength = sum of (confidence * exp(-age_hours / decay_hours))
        Recent signals weighted more heavily.
        """
        pass
    
    def get_strengthened_topics(
        self, 
        user: str, 
        threshold_increase: float = 0.1,
        window_hours: int = 6
    ) -> list[tuple[str, float, float]]:
        """
        Topics whose strength increased recently.
        
        Returns: [(topic, old_strength, new_strength), ...]
        Used to decide what to research.
        """
        pass
    
    def mark_researched(
        self, 
        user: str, 
        topic: str,
        cooldown_hours: int = 24
    ) -> None:
        """Mark a topic as researched to avoid re-triggering."""
        pass
    
    def should_research(
        self, 
        user: str, 
        topic: str,
        cooldown_hours: int = 24
    ) -> bool:
        """Has enough time passed since last research on this topic?"""
        pass
```

**SQL schema changes:**
```sql
-- Already exists, enhance it:
CREATE TABLE IF NOT EXISTS interest_nodes (
    id TEXT PRIMARY KEY,           -- topic
    label TEXT NOT NULL,           -- display name
    strength REAL NOT NULL,        -- current strength (0-1)
    confidence REAL NOT NULL,      -- avg confidence of signals
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_researched_at TEXT,       -- when we last researched this
    signal_count INTEGER DEFAULT 0 -- how many signals support this
);

-- Add indices for fast queries
CREATE INDEX IF NOT EXISTS idx_interest_user_strength 
    ON interest_nodes(user_id, strength DESC);
CREATE INDEX IF NOT EXISTS idx_interest_user_timestamp
    ON interest_nodes(user_id, updated_at DESC);
```

**Success criteria:**
- All 5 methods implemented and tested
- Strength calculation matches exponential decay formula
- Can query strengthened topics efficiently
- Cooldown prevents duplicate research triggers

---

### Task 3: Create Interest Agent (2-3 days)

**Files to create:**
- `src/agents/interest.py` (NEW) - The Interest Agent

**Structure:**
```python
class InterestAgent:
    """
    Consumes activity signals and maintains user interest model.
    
    Flow:
    1. Receive batch of signals from connectors
    2. Classify each into topics (via LLM)
    3. Update interest graph
    4. Detect strengthened topics
    5. Emit ResearchTopic commands for new/strengthened interests
    """
    
    def __init__(self, engine, llm, memory_store):
        self.engine = engine           # to submit ResearchTopic commands
        self.llm = llm                 # to classify signals
        self.memory = memory_store
        self.interest_graph = memory_store.interest_graph
    
    async def process_signals(
        self, 
        signals: list[ActivitySignal],
        user_id: str
    ) -> list[ResearchTopic]:
        """
        Main entry point. Returns list of research topics to trigger.
        
        Steps:
        1. Classify signals → InterestSignal objects
        2. Store in interest graph
        3. Calculate interest strengths
        4. Compare to previous → find strengthened
        5. Emit ResearchTopic commands
        """
        pass
    
    async def _classify_signals(
        self,
        signals: list[ActivitySignal]
    ) -> list[InterestSignal]:
        """
        Use LLM to extract topics from activity signals.
        
        Prompt: "What topics/interests does this activity signal indicate?
                 Respond with JSON: {topics: [str], confidences: [0-1 float]}"
        """
        pass
    
    async def _detect_research_triggers(
        self,
        user_id: str,
        interest_signals: list[InterestSignal]
    ) -> list[ResearchTopic]:
        """
        Compare new strength to old strength. 
        Emit ResearchTopic if increased by threshold.
        """
        pass
```

**Integration points:**
- Receives signals from daemon's ingest cycle
- Calls LLM for topic classification
- Stores results in Interest Graph
- Submits ResearchTopic commands to Engine
- Engine routes to Research Agent

**Success criteria:**
- Classify 10 sample signals correctly
- Store classifications in interest graph
- Detect topic with >10% strength increase
- Emit ResearchTopic command
- Same topic doesn't trigger twice in 24h

---

### Task 4: Wire into Daemon Loop (1 day)

**Files to modify:**
- `src/daemon/service.py` - Add Interest Agent initialization and scheduling
- `src/main_engine.py` - Pass interest agent reference to engine

**Changes:**
```python
class PersonalAssistantDaemon:
    def __init__(self, config):
        # ... existing code ...
        self.interest_agent = None
    
    async def initialize(self):
        # ... existing engine init ...
        # Create and store interest agent
        self.interest_agent = InterestAgent(
            engine=self.engine,
            llm=self.engine._llm,
            memory_store=self.engine._memory
        )
    
    async def _run_ingest_cycle(self):
        """Enhanced ingest cycle."""
        # Existing: collect signals from connectors
        all_signals = []
        for connector in get_enabled_connectors():
            signals = await connector.fetch(since=self._last_ingest)
            all_signals.extend(signals)
        
        if all_signals:
            self.logger.info(f"Processing {len(all_signals)} signals...")
            
            # NEW: Feed to Interest Agent
            research_topics = await self.interest_agent.process_signals(
                signals=all_signals,
                user_id="local"  # TODO: multi-user support
            )
            
            # Submit research topics to engine
            for topic in research_topics:
                await self.engine.submit(topic)
                self.logger.info(f"Research triggered: {topic.topic}")
```

**Success criteria:**
- Daemon initializes interest agent
- Ingest cycle calls interest agent
- Research topics submitted to engine
- Logs show signal flow

---

### Task 5: Integration Tests (1 day)

**Files to create:**
- `tests/test_signal_flow.py` (NEW)

**Test cases:**
```python
async def test_signal_to_interest_single_topic():
    """GitHub commit → classified as ML → stored in interest graph."""
    signal = ActivitySignal(
        source="github",
        event_type="commit",
        timestamp=datetime.now(),
        data={"repo": "ml-project", "message": "Add transformer model"}
    )
    
    # Classify
    interest_signals = await agent._classify_signals([signal])
    assert interest_signals[0].topics == ["machine learning"]
    assert interest_signals[0].confidences[0] > 0.7
    
    # Store
    await agent.interest_graph.add_classified_signal(...)
    
    # Retrieve
    strength = agent.interest_graph.get_strength("local", "machine learning")
    assert strength > 0

async def test_signal_triggers_research():
    """Interest strengthened → ResearchTopic emitted."""
    # Add old signal
    old_signal = make_signal("machine learning")
    await agent.process_signals([old_signal], "local")
    
    old_strength = agent.interest_graph.get_strength("local", "machine learning")
    
    # Add new signal (stronger evidence)
    new_signals = [
        make_signal("transformer models"),
        make_signal("attention mechanism"),
    ]
    research_topics = await agent.process_signals(new_signals, "local")
    
    # Should trigger
    assert len(research_topics) > 0
    assert research_topics[0].topic == "machine learning"

async def test_cooldown_prevents_duplicate_trigger():
    """Same topic doesn't trigger twice within 24h."""
    signal = make_signal("machine learning")
    
    # First time
    topics1 = await agent.process_signals([signal], "local")
    assert len(topics1) > 0
    
    # Second time (immediately after)
    topics2 = await agent.process_signals([signal], "local")
    assert len(topics2) == 0  # Cooldown prevents it

async def test_strength_decay():
    """Old signals matter less than recent ones."""
    agent = InterestAgent(...)
    
    # Add old signal
    old_signal = ActivitySignal(timestamp=datetime.now() - timedelta(days=30), ...)
    await agent.process_signals([old_signal], "local")
    
    # Add recent signal
    new_signal = ActivitySignal(timestamp=datetime.now(), ...)
    await agent.process_signals([new_signal], "local")
    
    # Recent should dominate
    strength = agent.interest_graph.get_strength("local", "topic", decay_hours=720)
    assert strength > 0.5  # Recent signal carries weight
```

**Success criteria:**
- All 4 test cases pass
- Integration test covers GitHub → Interest → Research flow
- Test can be run daily to catch regressions

---

## Execution Checklist

- [ ] Task 1: Define Interest Signal data models
- [ ] Task 2: Extend Interest Graph storage
- [ ] Task 3: Implement Interest Agent
- [ ] Task 4: Wire into daemon loop
- [ ] Task 5: Integration tests
- [ ] Manual verification: `pa daemon start` → watch logs for signal flow

---

## Verification Steps

After implementation:

```bash
# 1. Start daemon
pa daemon start

# 2. In another terminal, watch logs
pa daemon logs -f

# 3. Look for output like:
# [INFO] Got 5 signals from github
# [INFO] Processing 5 signals...
# [INFO] Classified into topics: machine learning (0.8), python (0.6)
# [INFO] Interest strength for "machine learning" increased from 0.4 to 0.7
# [INFO] Research triggered: machine learning (strength=0.7)

# 4. Run integration tests
pytest tests/test_signal_flow.py -v
```

Expected behavior: Signals flow through, get classified, update interests, trigger research.

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| LLM classification is noisy | Use confidence scores; require >0.6 to trigger |
| Threshold tuning | Ship conservative (long decay, high trigger), iterate |
| No signals to test with | Use fixture signals from tests |
| Research Agent not ready | Mock it, return success |

---

## Files Summary

### New Files
- `src/core/signals.py` - Interest signal data models
- `src/agents/interest.py` - Interest Agent implementation
- `tests/test_signal_flow.py` - Integration tests

### Modified Files
- `src/store/memory.py` - Interest graph methods
- `src/daemon/service.py` - Daemon integration
- `src/main_engine.py` - Agent initialization

### Configuration
- `config/settings.toml` - Add interest agent tuning knobs

---

## Success Definition

**DONE when:**
1. ✓ GitHub signal → classified as topic
2. ✓ Topic stored in interest graph with strength
3. ✓ Strength decay works (older signals matter less)
4. ✓ Topic triggering research when strengthened >10%
5. ✓ Cooldown prevents duplicate triggers
6. ✓ Daemon logs show full flow
7. ✓ All tests pass
