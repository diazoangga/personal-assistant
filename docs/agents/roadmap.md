# Agent Roadmap — Meta & Opportunity (planned)

Three of the five agents are implemented (Interest, Research, Brainstorming). Two remain
stubs. This doc records their intended shape so the seams already in the code make sense.

## Where the seams already exist

`core/engine.py` routes these command types today, but they raise until an agent is
registered under the matching name:

| Command | Handler | Needs agent | Status |
|---|---|---|---|
| `Opportunities(action=list/save/dismiss)` | `_handle_opportunities` | `opportunity` | not registered |
| `ShowDigest(date)` | `_handle_digest` | `opportunity` | not registered |

`main_engine.py` registers `interest`, `brainstorm`, `research`. Adding an agent is: build
it, `engine.register_agent("opportunity", agent)`, implement the methods the handlers call
(`list_opportunities`, `save_opportunity`, `dismiss_opportunity`, `build_digest`).

## Meta Agent (orchestrator)

**Intended role:** the supervisor — classify incoming activity at a higher level, decide
which agent should act, and review agent performance over time (were triggered research
runs useful? are interests drifting correctly?). Today there is a `agents/supervisor/`
stub. No orchestration policy is designed yet.

## Opportunity Agent (recommendations)

**Intended role:** synthesise the knowledge/concept graph + interest model into ranked,
provenance-carrying recommendations ("you keep reading about X and Y — here's an idea that
joins them"), and assemble a daily **digest**.

**Storage already in place:** the `opportunities` and `opportunity_interest_links` tables
exist in the unified store, so persistence is ready before the agent is.

## Build order

These are M6 in the [documentation-plan](../documentation-plan.md). Opportunity is the more
self-contained of the two (it reads existing graphs and writes `opportunities`); Meta is
broader and depends on having multiple agents worth orchestrating.

---

> **Source of truth:** `src/core/engine.py` (`_handle_opportunities`, `_handle_digest`),
> `src/agents/supervisor/`, `src/store/knowledge.py` (`opportunities*` tables).
