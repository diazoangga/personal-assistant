# Enhanced Ask Flow Implementation Plan

## Goal

Enhance the Personal Assistant's `ask` command to add cognitive capabilities:
1. **Conversation History Tracking** - Session-based Q&A storage
2. **Batch Interest Extraction** - Extract user interests from questions every N questions
3. **Quality-Based Knowledge Creation** - Store high-quality Q&A pairs as knowledge entries

## Current State Analysis

### What Works ✅
- Unified knowledge store exists with tables for interests, concepts, citations, and cross-references
- Engine initialization properly wires UnifiedKnowledgeStore to Engine constructor
- Interest Agent processes activity signals (GitHub/browser) but NOT user questions
- CLI has REPL mode for interactive conversations

### What's Missing ❌
- No conversation history tracking (no tables or methods)
- No question counter or session management
- Interest extraction only runs on external activity signals, not user questions
- No knowledge entry storage from Q&A interactions
- Current `ask()` method (line 111-127 in `main_engine.py`) calls LLM directly with no tracking

## Implementation Plan

### Phase 1: Database Schema Extensions (Priority: HIGH)

**File:** `src/store/knowledge.py`

**Task 1.1:** Add conversation history tables (~lines 225-270)
```sql
-- Session tracking
CREATE TABLE conversation_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    question_count INTEGER DEFAULT 0,
    metadata TEXT
);

-- Individual Q&A turns
CREATE TABLE conversation_turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    turn_number INTEGER NOT NULL,
    role TEXT NOT NULL,  -- 'user' or 'assistant'
    content TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    metadata TEXT,
    FOREIGN KEY (session_id) REFERENCES conversation_sessions(id) ON DELETE CASCADE
);

-- Knowledge entries from high-quality Q&A
CREATE TABLE knowledge_entries (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    quality_score REAL DEFAULT 0.5,
    source_session_id TEXT,
    user_id TEXT NOT NULL,
    embedded INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    metadata TEXT,
    FOREIGN KEY (source_session_id) REFERENCES conversation_sessions(id) ON DELETE SET NULL
);

-- User statistics tracking
CREATE TABLE user_stats (
    user_id TEXT PRIMARY KEY,
    total_questions INTEGER DEFAULT 0,
    total_knowledge_entries INTEGER DEFAULT 0,
    last_active TEXT,
    updated_at TEXT NOT NULL
);
```

**Task 1.2:** Add indexes for performance
```sql
CREATE INDEX idx_conversation_sessions_user ON conversation_sessions(user_id);
CREATE INDEX idx_conversation_turns_session ON conversation_turns(session_id);
CREATE INDEX idx_knowledge_entries_user ON knowledge_entries(user_id);
CREATE INDEX idx_knowledge_entries_quality ON knowledge_entries(quality_score DESC);
```

### Phase 2: Conversation Management Methods (Priority: HIGH)

**File:** `src/store/knowledge.py`

**Task 2.1:** Add session management methods (after line 647)
```python
async def create_conversation_session(
    self, 
    session_id: str, 
    user_id: str = "cli",
    metadata: dict[str, Any] = None
) -> None:
    """Create a new conversation session."""
    now = utcnow().isoformat()
    await self._db.execute("""
        INSERT INTO conversation_sessions (id, user_id, created_at, updated_at, question_count, metadata)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (session_id, user_id, now, now, 0, json.dumps(metadata) if metadata else None))
    await self._db.commit()

async def get_or_create_session(
    self, 
    session_id: str, 
    user_id: str = "cli"
) -> str:
    """Get existing session or create new one. Returns session_id."""
    cursor = await self._db.execute(
        "SELECT id FROM conversation_sessions WHERE id = ?",
        (session_id,)
    )
    row = await cursor.fetchone()
    if not row:
        await self.create_conversation_session(session_id, user_id)
    return session_id

async def add_conversation_turn(
    self,
    session_id: str,
    role: str,
    content: str,
    metadata: dict[str, Any] = None
) -> int:
    """Add a turn to a conversation session."""
    now = utcnow().isoformat()
    
    # Get current turn number
    cursor = await self._db.execute(
        "SELECT MAX(turn_number) as max_turn FROM conversation_turns WHERE session_id = ?",
        (session_id,)
    )
    row = await cursor.fetchone()
    turn_number = (row["max_turn"] or 0) + 1
    
    await self._db.execute("""
        INSERT INTO conversation_turns (session_id, turn_number, role, content, timestamp, metadata)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (session_id, turn_number, role, content, now, json.dumps(metadata) if metadata else None))
    
    # Update session question count and updated_at
    await self._db.execute("""
        UPDATE conversation_sessions 
        SET question_count = question_count + 1, updated_at = ?
        WHERE id = ?
    """, (now, session_id))
    
    await self._db.commit()
    return turn_number

async def get_conversation_history(
    self,
    session_id: str,
    limit: int = 50
) -> list[dict[str, Any]]:
    """Get conversation history for a session."""
    cursor = await self._db.execute("""
        SELECT * FROM conversation_turns 
        WHERE session_id = ? 
        ORDER BY turn_number DESC 
        LIMIT ?
    """, (session_id, limit))
    rows = await cursor.fetchall()
    return [dict(row) for row in reversed(rows)]

async def get_session_info(self, session_id: str) -> Optional[dict[str, Any]]:
    """Get session metadata."""
    cursor = await self._db.execute(
        "SELECT * FROM conversation_sessions WHERE id = ?",
        (session_id,)
    )
    row = await cursor.fetchone()
    return dict(row) if row else None

async def clear_conversation_history(self, session_id: str) -> None:
    """Clear all turns from a session."""
    await self._db.execute(
        "DELETE FROM conversation_turns WHERE session_id = ?",
        (session_id,)
    )
    await self._db.execute(
        "UPDATE conversation_sessions SET question_count = 0, updated_at = ? WHERE id = ?",
        (utcnow().isoformat(), session_id)
    )
    await self._db.commit()
```

**Task 2.2:** Add user statistics methods
```python
async def increment_user_question_count(self, user_id: str) -> int:
    """Increment user's question count and return new total."""
    now = utcnow().isoformat()
    
    await self._db.execute("""
        INSERT INTO user_stats (user_id, total_questions, last_active, updated_at)
        VALUES (?, 1, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            total_questions = total_questions + 1,
            last_active = excluded.last_active,
            updated_at = excluded.updated_at
    """, (user_id, now, now))
    
    cursor = await self._db.execute(
        "SELECT total_questions FROM user_stats WHERE user_id = ?",
        (user_id,)
    )
    row = await cursor.fetchone()
    await self._db.commit()
    return row["total_questions"]

async def get_user_stats(self, user_id: str) -> Optional[dict[str, Any]]:
    """Get statistics for a user."""
    cursor = await self._db.execute(
        "SELECT * FROM user_stats WHERE user_id = ?",
        (user_id,)
    )
    row = await cursor.fetchone()
    return dict(row) if row else None

async def increment_knowledge_entries(self, user_id: str) -> None:
    """Increment user's knowledge entry count."""
    now = utcnow().isoformat()
    await self._db.execute("""
        INSERT INTO user_stats (user_id, total_knowledge_entries, updated_at)
        VALUES (?, 1, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            total_knowledge_entries = total_knowledge_entries + 1,
            updated_at = excluded.updated_at
    """, (user_id, now, now))
    await self._db.commit()
```

**Task 2.3:** Add knowledge entry methods
```python
async def store_knowledge_entry(
    self,
    entry_id: str,
    question: str,
    answer: str,
    quality_score: float,
    user_id: str,
    session_id: str = None,
    metadata: dict[str, Any] = None
) -> None:
    """Store a high-quality Q&A pair as a knowledge entry."""
    now = utcnow().isoformat()
    
    await self._db.execute("""
        INSERT INTO knowledge_entries (id, question, answer, quality_score, source_session_id, user_id, created_at, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (entry_id, question, answer, quality_score, session_id, user_id, now, json.dumps(metadata) if metadata else None))
    
    await self.increment_knowledge_entries(user_id)
    await self._db.commit()

async def get_knowledge_entries(
    self,
    user_id: str = None,
    min_quality: float = 0.0,
    limit: int = 50
) -> list[dict[str, Any]]:
    """Get knowledge entries filtered by user and quality."""
    if user_id:
        cursor = await self._db.execute("""
            SELECT * FROM knowledge_entries 
            WHERE user_id = ? AND quality_score >= ?
            ORDER BY quality_score DESC, created_at DESC
            LIMIT ?
        """, (user_id, min_quality, limit))
    else:
        cursor = await self._db.execute("""
            SELECT * FROM knowledge_entries 
            WHERE quality_score >= ?
            ORDER BY quality_score DESC, created_at DESC
            LIMIT ?
        """, (min_quality, limit))
    
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]

async def search_knowledge_entries(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search knowledge entries by question/answer content."""
    cursor = await self._db.execute("""
        SELECT * FROM knowledge_entries 
        WHERE question LIKE ? OR answer LIKE ?
        ORDER BY quality_score DESC
        LIMIT ?
    """, (f"%{query}%", f"%{query}%", limit))
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]
```

### Phase 3: Batch Interest Extraction (Priority: HIGHEST)

**File:** `src/main_engine.py`

**Task 3.1:** Add instance variables to track question batches (~after line 37)
```python
self._question_counter: dict[str, int] = {}  # user_id -> count since last extraction
self._question_batch_buffer: dict[str, list[str]] = {}  # user_id -> list of recent questions
```

**Task 3.2:** Add batch interest extraction method (~after line 217)
```python
async def _extract_interests_from_batch(
    self,
    questions: list[str],
    user_id: str = "cli"
) -> list[str]:
    """
    Extract user interests from a batch of questions.
    
    Uses Interest Agent's classification on aggregated question topics.
    Returns list of extracted interest labels.
    """
    if not questions or not self._interest_agent:
        return []
    
    logger.info(f"Extracting interests from batch of {len(questions)} questions")
    
    # Aggregate questions into a single signal for classification
    aggregated_text = " ".join(questions)
    
    # Create synthetic activity signal from questions
    signal = {
        "id": f"question-batch-{utcnow().timestamp()}",
        "type": "user_questions",
        "content": aggregated_text,
        "timestamp": utcnow().isoformat(),
        "metadata": {
            "question_count": len(questions),
            "user_id": user_id,
        }
    }
    
    # Run through Interest Agent classifier
    try:
        results = await self._interest_agent.classify_signal(signal, user_id=user_id)
        
        # Extract topics that crossed confidence threshold
        extracted_interests = []
        for result in results:
            if result.get("confidence", 0) >= 0.6:  # Configurable threshold
                extracted_interests.append(result.get("topic", ""))
                
        logger.info(f"Extracted {len(extracted_interests)} interests from question batch")
        return extracted_interests
        
    except Exception as e:
        logger.warning(f"Interest extraction failed: {e}")
        return []
```

**Task 3.3:** Wire batch extraction into ask() flow
```python
# In the ask() method, replace lines 111-127 with:

async def ask(self, query: str, user: str = "cli", session_id: str = None) -> str:
    """Ask a question and return the answer."""
    from .core.commands import Ask
    import uuid
    
    assert self._engine is not None
    logger.info(f"Processing query: {query[:50]}...")
    
    # Initialize tracking for user if needed
    if user not in self._question_counter:
        self._question_counter[user] = 0
        self._question_batch_buffer[user] = []
    
    # Get or create session
    if not session_id:
        session_id = f"{user}-{utcnow().strftime('%Y%m%d')}"
    if self._knowledge_store:
        await self._knowledge_store.get_or_create_session(session_id, user)
    
    # Store question in conversation history
    if self._knowledge_store:
        await self._knowledge_store.add_conversation_turn(
            session_id=session_id,
            role="user",
            content=query,
            metadata={"type": "question"}
        )
        await self._knowledge_store.increment_user_question_count(user)
    
    # Add to batch buffer
    self._question_batch_buffer[user].append(query)
    self._question_counter[user] += 1
    
    # Check if we should extract interests from batch
    batch_size = self.config.get("agents", {}).get("interest", {}).get("batch_size", 5)
    extracted_interests = []
    
    if self._question_counter[user] >= batch_size:
        # Extract interests from batch
        questions_batch = self._question_batch_buffer[user].copy()
        extracted_interests = await self._extract_interests_from_batch(questions_batch, user)
        
        # Reset counter and buffer
        self._question_counter[user] = 0
        self._question_batch_buffer[user] = []
    
    # Call LLM for answer
    if not self._llm:
        raise RuntimeError("LLM not initialized")
    
    response = await self._llm.chat(
        messages=[{"role": "user", "content": query}],
        model_role="meta",
    )
    answer = response.content
    logger.debug(f"Query answered ({len(answer)} chars)")
    
    # Store answer in conversation history
    if self._knowledge_store:
        await self._knowledge_store.add_conversation_turn(
            session_id=session_id,
            role="assistant",
            content=answer,
            metadata={"type": "answer"}
        )
    
    # Assess answer quality and potentially store as knowledge entry
    quality_threshold = self.config.get("knowledge", {}).get("quality_threshold", 0.6)
    should_store = await self._assess_answer_quality(query, answer)
    
    if should_store and self._knowledge_store:
        entry_id = f"ka-{uuid.uuid4().hex[:12]}"
        await self._knowledge_store.store_knowledge_entry(
            entry_id=entry_id,
            question=query,
            answer=answer,
            quality_score=should_store,  # Use quality score as boolean proxy
            user_id=user,
            session_id=session_id,
            metadata={
                "extracted_interests": extracted_interests,
                "auto_stored": True
            }
        )
        logger.info(f"Stored knowledge entry: {entry_id} (quality={should_store})")
    
    return answer
```

### Phase 4: Quality Assessment Method (Priority: MEDIUM)

**File:** `src/main_engine.py`

**Task 4.1:** Add quality assessment method (~after the new _extract_interests_from_batch)
```python
async def _assess_answer_quality(
    self,
    question: str,
    answer: str,
    min_length: int = 100
) -> float:
    """
    Assess if an answer is high-quality enough to store as knowledge.
    
    Criteria:
    - Answer length (not too short)
    - Contains substantive information (not just acknowledgments)
    - Question is fact-seeking (not chit-chat)
    
    Returns quality score (0.0-1.0) or 0.0 if shouldn't store.
    """
    # Quick heuristic checks first
    if len(answer) < min_length:
        return 0.0
    
    # Avoid storing conversational filler
    filler_patterns = [
        "i think", "i believe", "in my opinion",
        "that's a great question", "thank you for asking",
        "as an ai", "as a language model"
    ]
    answer_lower = answer.lower()
    if any(pattern in answer_lower for pattern in filler_patterns):
        return 0.0
    
    # Use LLM for quality scoring
    if not self._llm:
        return 0.0
    
    quality_prompt = f"""
Rate the quality of this Q&A pair for knowledge storage (0.0-1.0):

Question: {question}

Answer: {answer}

Criteria:
- Factual accuracy and specificity (not vague)
- Educational value (teaches something useful)
- Completeness (answers the full question)
- Verifiability (contains concrete information, not opinions)

Respond with ONLY a number between 0.0 and 1.0 (e.g., "0.75").
"""
    
    try:
        response = await self._llm.chat(
            messages=[{"role": "user", "content": quality_prompt}],
            model_role="meta",
        )
        
        # Parse score from response
        score_text = response.content.strip()
        # Extract number from text
        import re
        match = re.search(r'(\d\.?\d*)', score_text)
        if match:
            score = float(match.group(1))
            return max(0.0, min(1.0, score))
        return 0.0
        
    except Exception as e:
        logger.warning(f"Quality assessment failed: {e}")
        return 0.0
```

### Phase 5: Configuration Updates (Priority: MEDIUM)

**File:** `config/settings.toml`

**Task 5.1:** Add new configuration sections (~after line 54)
```toml
[agents.interest]
# Batch processing for question-based interest extraction
batch_size = 5                    # Extract interests every N questions
min_confidence = 0.6              # Minimum confidence to accept extracted interest
embedding_cache_enabled = true    # Cache embeddings for hybrid classification

[knowledge]
# Quality-based knowledge entry storage
quality_threshold = 0.65          # Minimum quality score to auto-store Q&A
auto_embed = false                # Don't embed immediately (lazy embedding)
max_entries_per_user = 1000       # Limit to prevent unbounded growth

[conversation]
# Session management
session_limit = 100               # Max turns per session before auto-truncate
auto_create = true                # Auto-create sessions in REPL mode
persist_across_restarts = true    # Keep session IDs between CLI restarts
```

### Phase 6: CLI Enhancements (Priority: LOW)

**File:** `src/adapters/cli/app.py` (needs to be located and reviewed)

**Task 6.1:** Add new CLI commands
```python
# History command
@app.command("history")
async def history_cmd(
    session: str = typer.Option(None, help="Session ID to view"),
    limit: int = typer.Option(20, help="Number of turns to show"),
    clear: bool = typer.Option(False, help="Clear history instead of viewing"),
):
    """View or clear conversation history."""
    # Implementation: call knowledge_store.get_conversation_history()

# Knowledge command
@app.command("knowledge")
async def knowledge_cmd(
    search: str = typer.Option(None, help="Search query"),
    min_quality: float = typer.Option(0.5, help="Minimum quality threshold"),
    limit: int = typer.Option(20, help="Number of entries to show"),
):
    """Search stored knowledge entries."""
    # Implementation: call knowledge_store.search_knowledge_entries()

# Stats command  
@app.command("stats")
async def stats_cmd():
    """Show user statistics."""
    # Implementation: call knowledge_store.get_user_stats()
```

### Phase 7: Testing (Priority: MEDIUM)

**Files to Create:**
- `tests/test_conversation_sessions.py` - Session CRUD operations
- `tests/test_batch_interest_extraction.py` - Batch processing logic
- `tests/test_knowledge_quality.py` - Quality assessment heuristics
- `tests/test_ask_flow_integration.py` - Full integration tests

**Test Coverage:**
- Session creation and retrieval
- Turn tracking and ordering
- Question counter increments correctly
- Batch extraction triggers at correct interval
- Quality scoring rejects low-quality answers
- High-quality answers are stored with correct metadata
- User stats update correctly

## Configuration Decisions Needed

### From User Preferences (stated earlier):

1. **Batch Size**: User didn't confirm exact number
   - **Recommendation**: Start with `batch_size = 5`
   - Trade-off: Larger batches = more context but slower interest updates

2. **Quality Threshold**: User didn't confirm exact value
   - **Recommendation**: Start with `quality_threshold = 0.65`
   - Trade-off: Higher = fewer but better entries; Lower = more comprehensive but noisier

3. **Session Persistence**: User didn't confirm
   - **Recommendation**: `persist_across_restarts = true`
   - Allows continuing conversations across CLI sessions

4. **Embedding Strategy**: User didn't confirm
   - **Recommendation**: `auto_embed = false` (lazy embedding)
   - Embed on-demand when searching to save resources

## Execution Order

1. ✅ **Phase 1** - Schema extensions (foundation)
2. ✅ **Phase 2** - Conversation methods (enables tracking)
3. ✅ **Phase 3** - Batch interest extraction (HIGHEST priority feature)
4. ✅ **Phase 4** - Quality assessment (enables knowledge storage)
5. ✅ **Phase 5** - Configuration (wires it all together)
6. ⏸️ **Phase 6** - CLI commands (nice-to-have, can be done later)
7. ⏸️ **Phase 7** - Tests (important but can follow implementation)

## Files to Modify Summary

| File | Changes | Priority |
|------|---------|----------|
| `src/store/knowledge.py` | Add 4 tables, ~15 new methods | HIGH |
| `src/main_engine.py` | Enhance `ask()`, add 3 new methods | HIGHEST |
| `config/settings.toml` | Add 3 new config sections | MEDIUM |
| `src/adapters/cli/app.py` | Add 3 new commands | LOW |
| `tests/test_*.py` | Create 4 test files | MEDIUM |

## Dependencies & Risks

### Dependencies
- Interest Agent must be initialized and working (already done ✅)
- LLM runtime must support quality assessment calls (already have `_llm.chat()`)
- JSON module needed for metadata serialization

### Risks
1. **Performance**: Quality assessment adds extra LLM call per question
   - Mitigation: Make it async, consider caching similar Q&A assessments
   
2. **Database Size**: Unbounded growth of conversation history
   - Mitigation: Implement auto-truncation, session limits, TTL policies

3. **Interest Noise**: Extracting from every question could create noisy interests
   - Mitigation: Batch processing + confidence thresholds (already planned ✅)

4. **Storage Costs**: Storing all high-quality Q&A could use significant space
   - Mitigation: Quality threshold, max entries per user config options

## Next Steps

Ready to proceed with implementation in this order:
1. Modify `src/store/knowledge.py` - Add tables and methods
2. Modify `src/main_engine.py` - Enhance ask flow with tracking, batching, quality
3. Update `config/settings.toml` - Add new sections
4. Test manually with REPL mode
5. Create automated tests
6. Add CLI commands (optional enhancement)
