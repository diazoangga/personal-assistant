# Interest Agent

Turns raw activity into a decaying model of what the user cares about, and decides when a
topic is worth researching. It is the entry point of the proactive loop.

## Responsibilities

1. **Classify** activity signals into topics (semantic match first, LLM fallback).
2. **Store** each `(topic, confidence, timestamp)` as evidence.
3. **Score** interest strength with exponential decay.
4. **Trigger** research when a topic crosses the strength threshold off cooldown.

`process_signals(signals, user_id) -> list[ResearchTopic]` is the single public entry
point; callers (daemon, CLI/API question batch) submit the returned commands.

## Classification: hybrid, LLM-sparing

For each signal, `_signal_to_text` flattens it to a line (source, event type, the salient
fields per source). Then:

| Step | What happens |
|---|---|
| 1 | Load cached interest embeddings with `strength > 0.2`. |
| 2 | Embed the signal text once (`llm.embed`). |
| 3 | Cosine-compare to each cached interest; keep matches `> 0.6`. |
| 4 | If any match → take top 2 as the classification (`model_version="hybrid-v1"`), **no LLM call**. |
| 5 | Else → `_classify_with_llm` (`role="reasoning"`) returns `{topics, confidences, explanation}`. |
| 6 | Cache the primary topic's embedding for next time. |

The whole point of step 4 is to avoid an LLM call on the common case once the interest
model exists.

## Strength & decay

Strength is derived from evidence on every read, never stored as a counter:

```
strength(topic) = Σ_i  confidence_i · exp(-age_hours_i / 720)
```

720 hours ≈ 30 days. Implemented in `store.get_strength`. This is why the **original signal
timestamp must survive** the whole pipeline (decay is age-based).

## Triggering

```
for topic in classified topics:
    if not store.should_research(topic, cooldown_hours=24):  continue   # 24h cooldown
    if store.get_strength(topic) > 0.3:                                  # threshold
        store.mark_researched(topic)                                    # start cooldown
        emit ResearchTopic(topic, depth = "deep" if strength>=0.7 else "normal")
```

Cooldown is tracked in `interest_research_log` (a per-topic `last_researched_at`), kept
separate from `interests.last_active`.

## Tables it owns

| Table | Role |
|---|---|
| `interest_signal_evidence` | one row per `(signal_id, topic)` with confidence + timestamp — the raw material for decay. |
| `interests` | the topic nodes (label, strength snapshot, timestamps). |
| `interest_embeddings` | cached topic embeddings for semantic matching. |
| `interest_research_log` | per-topic research cooldown. |

## Construction

```python
InterestAgent(engine, llm, memory: UnifiedKnowledgeStore, config=None)
# embedding_model default: qwen/qwen3-embedding-8b
```

## Gotchas

- **Timestamps** — never substitute `datetime.utcnow()` for the signal's real time.
- **Confidence/topic length mismatch** — LLM output is validated; `len(topics) ==
  len(confidences)` or the classification is dropped.
- **Cooldown vs strength** — a strong topic still won't re-trigger inside 24 h.

---

> **Source of truth:** `src/agents/interest.py`, `src/core/signals.py`,
> `src/store/knowledge.py`. Flow context: [architecture/signal-flow.md](../architecture/signal-flow.md).
