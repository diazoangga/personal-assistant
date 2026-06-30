---
title: "Implementation: Activity Sensing Pipeline"
created: 2026-06-20
updated: 2026-06-21
version: 3.0.0
status: Draft
tags: [implementation, ingestion, sensing, signals, connectors, activity]
changelog:
  - version: 1.0.0
    date: 2026-06-20
    changes: "Initial Daily Research Agent (SDLC builder Loop 1)"
  - version: 2.0.0
    date: 2026-06-21
    changes: >-
      Rewritten as the Ingestion & Sensing pipeline (Loop A) for the cognitive
      engine. Generalized 'sources' to 'connectors' (GitHub/browser/Slack/calendar
      added to RSS/arXiv/HN), emit signal events for the Interest Agent, and
      reframed the digest as a proactive insight digest. Merges what an earlier
      draft split into 'Knowledge Agent' and 'Research Radar Agent'. (Filename kept
      to preserve cross-links.)
  - version: 3.0.0
    date: 2026-06-21
    changes: >-
      Narrowed scope (plans.md v4.0.0). Research-source connectors (arXiv, GitHub
      trending, Medium, news) and the resulting Knowledge Base writes moved to the
      new Research Agent ([06-research-agent.md](06-research-agent.md)), which is
      triggered by the Interest Agent rather than pulled on a blind schedule. This
      pipeline now does exactly one job: turn **activity** signals (what you do)
      into the feed the Interest Agent classifies. Insight-digest building moved to
      the Opportunity Agent ([05-meta-agent-and-skills.md](05-meta-agent-and-skills.md) §5)
      since it now synthesizes across Research Agent findings, not just this
      pipeline's output. (Filename kept again to preserve cross-links; content has
      fully turned over twice now — a rename is worth reconsidering, see the note
      at the bottom.)
related:
  - ../personal-assistant.plans.md
  - 03-vector-db-and-storage.md
  - 06-research-agent.md
---

> Whenever this documentation file changes, update the `updated` field and append a new entry to `changelog` describing the revision.

# Implementation: Activity Sensing Pipeline

> **This is a pipeline, not an agent.** It pulls **activity** signals, normalizes,
> dedupes, and emits them — a fixed transform with no goals and no decisions. Per D4
> that makes it a pipeline of skills/tools, not an agent. (It is the activity half
> of what an earlier draft over-split into a "Knowledge Agent" and a "Research Radar
> Agent"; the research half is now the **Research Agent** — a real decider — in
> [06-research-agent.md](06-research-agent.md).)

It runs on a schedule, independent of any user command. Its only job is to keep the
**Interest Agent** fed with a true picture of what the user is doing — browsing,
committing code, meetings, conversations. It does **not** write to the Knowledge
Base; that's the Research Agent's job, triggered by what this pipeline indirectly
causes the Interest Agent to classify.

```
scheduler (sensing_cron)
      │
      ▼
  pull activity connectors ─► normalize ─► dedupe ─► tag ─► store (signal log)
                                                                  │
                                                                  ▼
                                                   emit Signal events ──► Interest Agent
                                                                              │
                                                                              ▼
                                                              (classification may trigger
                                                               the Research Agent — see
                                                               05-meta-agent-and-skills.md §4)
```

---

## 1. Connectors (pluggable, activity-only)

Each connector is a small adapter returning normalized `RawSignal`s. Adding one is
adding a file — no pipeline changes.

```python
# src/ingest/connectors/base.py
@dataclass
class RawSignal:
    title: str
    url: str | None
    body: str
    connector: str        # "github" | "browser" | "slack" | "calendar"
    occurred_at: str

class Connector(Protocol):
    async def fetch(self, since: str) -> list[RawSignal]: ...
```

| Connector | File | Notes |
|-----------|------|-------|
| GitHub (your activity) | `connectors/github.py` | your commits/repos/stars — **not** trending repos; that's the Research Agent's `github_research` connector, a different file and a different caller. **Build first.** |
| Browser history | `connectors/browser.py` | **opt-in, M3** — strongest interest signal, most sensitive |
| Slack | `connectors/slack.py` | **opt-in, M3** — your conversations as signal |
| Calendar | `connectors/calendar.py` | **opt-in, M3** — activity context |

> There is no `kind` field anymore (research vs activity) — everything this
> pipeline touches *is* activity. If you're adding a connector that returns
> research content (papers, articles, trending repos), it belongs in
> `src/research/connectors/` and is called by the Research Agent, not here. See
> [06-research-agent.md §3](06-research-agent.md#3-source-connectors-pareasarchconnectors).

---

## 2. The Pipeline

```python
# src/ingest/pipeline.py
async def sense(signals: list[RawSignal]) -> SensingReport:
    signals = dedupe(signals)                           # content-hash; drop known
    for s in signals:
        memory.log_signal(s)                            # raw signal log
    await bus.publish_signals(signals)                   # → Interest Agent
    return SensingReport(signals=len(signals))
```

No chunking, no embedding, no Knowledge Base write — this pipeline's only store is
the `signals` table in Persistent Memory (see
[03-vector-db-and-storage.md §2](03-vector-db-and-storage.md#2-persistent-memory-sqlite--the-user-model)).
That's what makes it a fixed transform rather than an agent: there is nothing to
decide here, only normalize-and-forward.

### Deduplication
Content-hash on `(connector, title, occurred_at)` — re-sensing the same activity
window is a no-op.

---

## 3. Scheduling & Compute Safety

```toml
[schedule]
sensing_cron    = "0 * * * *"    # this pipeline: hourly
understand_cron = "0 7 * * *"    # Interest Agent rollup
```

- **Scheduler:** cron calling `pa ingest now`, or APScheduler in a long-running
  engine. Either submits an `IngestNow` command — the same path manual `/ingest`
  uses (parity).
- **Concurrency guard:** this pipeline does no LLM/embedding work itself (no
  chunking), so it doesn't compete for VRAM the way the Research Agent does. Keep
  it that way — if a future activity connector needs classification at fetch time,
  push that into the Interest Agent instead of adding model calls here.

---

## 4. Privacy & Retention (gates the M3 connectors)

The personal connectors (browser, Slack, calendar) are the strongest signals **and**
the most sensitive. Before enabling any of them:
- **Opt-in per connector** in `config/settings.toml`.
- **Local-only (D1):** signals never leave the machine; all inference is local.
- **Retention policy:** an aging job prunes raw activity signals after N days; pin
  anything referenced by a saved opportunity.

---

## 5. Testing

- **Connectors:** record/replay fixtures (VCR-style); assert normalization to `RawSignal`.
- **Dedup:** overlapping batches → no duplicate signal rows.
- **Signal emission:** assert every sensed signal reaches the Interest Agent's queue.
- **Bridge test:** sense a fixture activity batch, run the Interest Agent, assert
  the resulting classification is what triggers (or correctly doesn't trigger) a
  Research Agent run.

---

## A note on this file's name

This is the second time this file's content has fully turned over while the
filename stayed `04-daily-research-agent.md` for cross-link stability. It no longer
describes a research agent at all — it describes activity sensing. If you're
touching this area of the docs next, consider `git mv` to
`04-activity-sensing-pipeline.md` and fixing the handful of relative links (this
doc, plus [05](05-meta-agent-and-skills.md), [06](06-research-agent.md), and
[plans.md](../personal-assistant.plans.md) all reference it by current filename).
Not done here to avoid an unrequested rename mid-revision.

---

## Related
- [03-vector-db-and-storage.md](03-vector-db-and-storage.md) — the signal log this pipeline fills
- [06-research-agent.md](06-research-agent.md) — what the Interest Agent's classification triggers next
- [05-meta-agent-and-skills.md](05-meta-agent-and-skills.md) — the Interest Agent consumer; Opportunity Agent (digest)
- [../personal-assistant.implementation.md](../personal-assistant.implementation.md)
