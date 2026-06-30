# Signal Flow

How raw activity becomes an interest, and how an interest becomes an autonomous research
run. This is the spine of the "proactive" behaviour.

## Pipeline

```
ActivitySignal(s)            (daemon polls connectors, or CLI/API batches questions)
      │
      ▼  InterestAgent.process_signals()
 ┌────────────────────────────────────────────────────────────────────┐
 │ 1. CLASSIFY   signal → topics                                       │
 │    a. embed signal text; cosine-match vs cached interest embeddings │
 │    b. if top match > 0.6  → reuse topic   (no LLM call)             │
 │    c. else                → LLM classify  → topics + confidences    │
 │ 2. STORE      add_classified_signal(topic, confidence, timestamp)   │
 │               → interest_signal_evidence                            │
 │ 3. DECAY      strength = Σ confidence·exp(-age_hours / 720)         │
 │ 4. TRIGGER    if strength > 0.3 and off 24h cooldown:               │
 │                 mark_researched(topic)                              │
 │                 emit ResearchTopic(topic, depth)                    │
 └────────────────────────────────────────────────────────────────────┘
      │  list[ResearchTopic]
      ▼
 daemon/engine submits each → Engine._handle_research → Research Agent
```

## Classification (hybrid, LLM-sparing)

`InterestAgent._classify_signals` tries semantic matching **before** spending an LLM call:

1. Load cached interest embeddings with `strength > 0.2`
   (`store.get_interest_embeddings`).
2. Embed the signal text once; cosine-compare to each cached interest.
3. If one or more interests score `> 0.6`, take the top 2 as the classification (model
   version `hybrid-v1`) — no LLM call.
4. Otherwise call the LLM (`role="reasoning"`) for `{topics, confidences, explanation}`
   and cache the new topic's embedding.

This is designed to cut LLM calls by ~70% once the interest model is established. Signal
text is built by `_signal_to_text` per source (github commit/PR, browser search/visit,
slack message).

## Strength & decay

Interest strength is recomputed from evidence, not stored as a running total:

```
strength(topic) = Σ_i  confidence_i · exp(-age_hours_i / 720)
```

The 720-hour (30-day) half-life-ish constant means a signal's contribution decays to ~37%
after 30 days. `get_strength` reads all `interest_signal_evidence` rows for the topic and
sums the decayed confidences. Because decay is computed on read, **the original signal
timestamp must be preserved** end-to-end — using `datetime.utcnow()` instead of the
activity's real time silently corrupts decay (see Gotchas).

## Triggering

A topic triggers research when:

- `get_strength(topic) > 0.3` (the `strength_threshold`), **and**
- `should_research(topic, cooldown_hours=24)` is true — i.e. it wasn't researched in the
  last 24 h (tracked in `interest_research_log`, separate from the interest's
  `last_active`).

On trigger, `mark_researched(topic)` starts the cooldown and a `ResearchTopic` command is
emitted with `depth = "deep"` if strength ≥ 0.7 else `"normal"`. The daemon submits these
via `engine.submit()`; the CLI/API question path batches them too
(`PersonalAssistantEngine._extract_interests_from_batch`).

## Two entry points

| Caller | Source of signals |
|---|---|
| **Daemon** | `connector.fetch(since=last_ingest)` every `ingest_interval_minutes` → `engine.process_activity_signals()` (see [ops/daemon.md](../ops/daemon.md)). |
| **CLI / API** | After every `batch_size` (default 5) questions, the engine bundles them into one `user_questions` `ActivitySignal` and runs the same path. |

## Gotchas

- **Timestamp propagation** — interest signals must carry the activity's real `timestamp`,
  not `datetime.utcnow()`, or decay math breaks.
- **Cooldown ≠ last_active** — research cooldown lives in `interest_research_log`; don't
  conflate it with `interests.last_active`.

---

> **Source of truth:** `src/agents/interest.py`,
> `src/store/knowledge.py` (`add_classified_signal`, `get_strength`, `should_research`,
> `mark_researched`, `get_interest_embeddings`), `src/core/signals.py`.
