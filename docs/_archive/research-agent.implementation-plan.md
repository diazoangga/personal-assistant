---
title: "Research Agent — Implementation Plan"
created: 2026-06-23
updated: 2026-06-23
version: 1.0.0
status: Ready to execute (pending data-model build)
tags: [research-agent, implementation-plan, citation-graph, knowledge-graph, semantic-scholar]
related:
  - research-agent.data-model.md
  - impl/06-research-agent.md
  - personal-assistant.signal-flow.implementation-plan.md
  - SYSTEM_DOCUMENTATION.md
reference:
  - https://api.semanticscholar.org/api-docs/graph
  - https://arxiv.org/help/api
---

> Whenever this file changes, bump `updated` and add a changelog entry.

# Research Agent — Implementation Plan

Builds the Research Agent on top of
[research-agent.data-model.md](research-agent.data-model.md). **Read the data-model doc
first** — this plan assumes that schema.

**Goal:** a real Research Agent that, given a topic (manual or from an Interest trigger),
discovers papers, **follows citations** to build a litmaps-style **citation graph**, extracts
concepts into a **knowledge graph**, **synthesizes** per-paper conclusions/notes, **links
everything to the originating interest**, and updates both graphs **incrementally** on every
run — all persisted in `knowledge.db`.

**Effort:** ~8–11 days. **Phase:** 1 (Research Agent), supersedes the rolled-back stub.

---

## 1. Current state (ground truth, 2026-06-23)

| Thing | Reality | Implication |
|---|---|---|
| `main_engine.research()` | **Stub** — prompts the LLM, returns text. No fetch/store/graph. | Replace entirely. |
| `src/agents/research/agent.py` | **Gone** (rolled back; only `.pyc`). `tools/`, `skills/` source also gone. | Greenfield agent + tools + skills. |
| `"research"` agent registration | Not registered in `PersonalAssistantEngine.initialize()`. | Wire it (Path A + Path B). |
| `citations` / `citation_relationships` | Tables exist; edges never written; node lacks conclusion/notes/url/tldr. | Extended by data-model build. |
| `src/store/graph.py` | Orphaned parallel `CitationGraph`/`KnowledgeGraph`. | Delete after agent uses `UnifiedKnowledgeStore`. |
| `ResearchTopic` command + `ShowGraph` | Defined in `commands.py`; handlers partial. | Reuse; finish `_handle_research` / `_handle_graph`. |

> SYSTEM_DOCUMENTATION.md §4.2 describes a research agent **as if implemented** — that
> section is aspirational and will be re-synced from code after this build.

---

## 2. Architecture

```
ResearchTopic(topic, depth)            Interest Agent trigger
   (pa research / brainstorm)          (ResearchTopic w/ interest_id)
            │                                    │
            └──────────────┬─────────────────────┘
                           ▼
                    ResearchAgent.research(topic, interest_id?, depth?, publish?, job_id?)
   ┌───────────────────────────────────────────────────────────────────────────┐
   │ 1. REUSE     get_existing_research(topic, interest_id) → decide depth       │  ◀ decision
   │ 2. SEED      Semantic Scholar search (+ arXiv supplementary)                │  ◀ decision: sources
   │ 3. EXPAND    follow references + citations  → citation edges (BFS, novelty) │  ◀ decision: keep chasing?
   │ 4. ENRICH    LLM: conclusion + notes per new paper                          │
   │ 5. EXTRACT   entity_extraction + relation_extraction → concept graph        │  ◀ decision: novelty/dedup
   │ 6. LINK      papers↔concepts, interest↔papers, interest↔concepts            │
   │ 7. PERSIST   idempotent upserts; record research_run delta                  │
   │ 8. SUMMARIZE LLM "what's new", cited                                        │
   └───────────────────────────────────────────────────────────────────────────┘
                           │
              UnifiedKnowledgeStore (knowledge.db) + Qdrant (abstract embeddings)
```

The four **decision points** (depth, source priority, citation-chase continuation, novelty)
are what make this an agent per the D4 litmus test in
[impl/06-research-agent.md §2](impl/06-research-agent.md). They are explicit methods, not a
fixed pipeline.

**No native tool-calling required.** Per the OpenRouterRuntime constraint (it flattens
messages to a prompt and returns text — no `tool_calls`), the agent is a **structured
pipeline with LLM decision/extraction steps**, each a discrete `llm.chat(...)` call returning
parseable JSON. This avoids the LangChain `bind_tools` dependency that the Brainstorming Agent
debated; the Research Agent does not need an open-ended tool loop.

---

## 3. Phases & tasks

Each phase is independently testable. Order matters: the data model underpins everything.

### Phase R1 — Data model (2 days) — *do first*

Implements [research-agent.data-model.md](research-agent.data-model.md) §4–§8.

**Files:** `src/store/knowledge.py`, `tests/test_research_store.py`

- [ ] Add migration helper `_add_column_if_missing` and apply new `citations` / `concepts` columns.
- [ ] Recreate `citation_relationships` with `UNIQUE(source_id,target_id,relationship_type)` + indexes.
- [ ] `CREATE TABLE` for `interest_citation_links`, `research_runs`.
- [ ] Implement store methods from data-model §6 (`upsert_citation` extended,
      `add_citation_edge`, `get_citation_edges`, `is_known_citation`, `citation_subgraph`,
      `update_citation_notes`, `link_interest_to_citation`, `get_citations_for_interest`,
      `get_existing_research`, `start_research_run`, `finish_research_run`, `get_research_runs`).
- [ ] `compute_citation_id(paper)` helper (doi → arxiv_id → s2_id → title-hash).
- [ ] **Tests:** re-running an upsert doesn't duplicate; citation edges are directed and
      idempotent; `citation_subgraph` BFS returns the expected nodes/edges; `get_existing_research`
      returns prior papers for an interest.

**Acceptance:** schema migrates an existing `knowledge.db` non-destructively; all store tests green.

### Phase R2 — Source connectors (2 days)

**Files:** `src/agents/research/tools/semantic_scholar.py` (primary),
`src/agents/research/tools/arxiv_connector.py` (restore, supplementary),
`src/agents/research/tools/base.py`, `tests/test_research_connectors.py`

- [ ] `ResearchConnector` protocol: `async search(topic, limit) -> list[RawPaper]`.
- [ ] **Semantic Scholar** (`httpx`, async):
  - `search_papers(query, limit, fields=[paperId,title,abstract,authors,year,venue,url,tldr,citationCount,referenceCount,influentialCitationCount,externalIds])`
  - `get_references(paper_id)` and `get_citations(paper_id)` → the citation frontier (G2).
  - Respect rate limits (unauthenticated ~100 req / 5 min); read `SEMANTIC_SCHOLAR_API_KEY`
    from env if present (header `x-api-key`); exponential backoff on 429.
- [ ] **arXiv** (restore prior connector): `search(topic, limit)` over
      `https://export.arxiv.org/api/query` (HTTPS — 301 isn't auto-followed). Supplementary
      fresh-preprint source; maps into the same `RawPaper`.
- [ ] `RawPaper` dataclass normalizes both sources → the `citations` upsert shape, with
      `externalIds` populating `doi` / `arxiv_id` / `semantic_scholar_id` for cross-source merge.
- [ ] **Tests:** record/replay (VCR-style) fixtures per connector; assert normalization and
      that references/citations parse into edge tuples. No live network in CI.

**Acceptance:** given a topic, Semantic Scholar returns normalized papers + reference/citation
IDs; arXiv returns normalized papers; both offline-testable.

### Phase R3 — Skills (2 days)

**Files:** `src/agents/research/skills/entity_extraction.py` (restore),
`src/agents/research/skills/relation_extraction.py`,
`src/agents/research/skills/paper_synthesis.py`,
`src/agents/research/skills/summarization.py`, `tests/test_research_skills.py`

- [ ] **entity_extraction** — LLM over an abstract → typed concepts
      (`concept/method/model/task/dataset/metric/framework`) with confidence; drop `< min_entity_confidence`
      (0.6); dedup highest-confidence per `(name, type)`. (Restores prior behavior.)
- [ ] **relation_extraction** — second LLM pass over the concept set → typed edges from the
      closed vocab (`uses/extends/competes_with/evaluated_on/part_of/related_to`) with weight + evidence.
- [ ] **paper_synthesis** — LLM over `abstract + tldr` → `{conclusion: str, notes: {key_contributions, methods, limitations}}` (G4, locked: abstract-level, no PDF).
- [ ] **summarization** — LLM over the run's new papers/concepts → one cited "what's new" paragraph (`research_runs.summary`).
- [ ] All skills take an injectable `llm` and return parsed JSON; **FakeLLM** in tests (pattern
      from CLAUDE.md "Mocking LLMs").
- [ ] **Tests:** malformed-JSON tolerance; confidence filtering; closed-vocab enforcement.

**Acceptance:** each skill deterministic under FakeLLM; entity/relation/synthesis outputs match the store shapes.

### Phase R4 — The agent (2 days)

**Files:** `src/agents/research/agent.py`, `src/agents/research/__init__.py`, `tests/test_research_agent.py`

- [ ] `ResearchAgent(llm, store, connectors, config)` with
      `async research(topic, *, interest_id=None, depth=None, trigger_source="manual", publish=None, job_id=None) -> dict`.
- [ ] Implement the 8 steps (§2). Decision methods kept explicit and unit-testable:
  - `_decide_depth(topic, existing, trigger_strength)` — new strong interest → `deep`; thin reinforcement with lots of prior research → `shallow`/skip.
  - `_prioritize_sources(topic, depth)` — theory-ish topics weight Semantic Scholar/arXiv; tooling weights arXiv less. (Returns ordered source list.)
  - `_worth_chasing(paper, frontier_size, hops)` — bounded by `max_citation_depth`; stop on diminishing novelty.
  - `_is_novel(citation_id)` → `not store.is_known_citation(...)`.
- [ ] Citation BFS populates `citation_relationships` as it expands (G2/G4).
- [ ] Every new paper → `link_interest_to_citation`; every concept → `link_interest_to_concept`
      and `link_citation_to_concept` (G6). Re-runs re-weight, never duplicate (G5).
- [ ] Wrap in `start_research_run` / `finish_research_run` with deltas; emit `Progress` events
      when `publish`/`job_id` set (Path B).
- [ ] **Tests:** (a) re-run same topic twice → second run adds 0 new nodes, updates weights;
      (b) citation frontier expands to `max_citation_depth` then stops; (c) decision methods
      vary with input (not constant — that would mean it regressed to a pipeline);
      (d) interest links created for the originating interest.

**Acceptance:** end-to-end with FakeLLM + replayed connectors produces papers, cites edges,
concepts, concept edges, interest links, and a `research_runs` row — all in a temp DB.

### Phase R5 — Wiring & CLI (1–2 days)

**Files:** `src/main_engine.py`, `src/core/engine.py`, `src/adapters/cli/app.py`,
`config/settings.toml`, `tests/test_phase1_integration.py`

- [ ] Construct `ResearchAgent` in `PersonalAssistantEngine.initialize()` and
      `engine.register_agent("research", agent)`.
- [ ] **Replace `main_engine.research()` stub** with a call into the agent (Path A): records
      interest @0.85, passes `interest_id`, awaits `agent.research(...)`, returns the summary +
      counts.
- [ ] Finish `Engine._handle_research` → `"research"` agent with `Progress`/`Result` events (Path B,
      used by the daemon). Pass `interest_id` from the `ResearchTopic` trigger so daemon-driven
      research links to the interest that caused it.
- [ ] Interest Agent trigger: thread `interest_id`/topic through `ResearchTopic` so the agent
      can link results back (G6). Update `interest_research_log` cooldown on completion.
- [ ] `pa research "<topic>" [-d N]` → real pipeline; print summary + "N new papers, M concepts".
- [ ] `pa graph --kind citation|knowledge [--topic X]` → `_handle_graph` renders
      `citation_subgraph` / `relevant_subgraphs` (counts + top nodes; JSON via `--json` for a future UI).
- [ ] `config/settings.toml [agents.research]`: `semantic_scholar_max_results`,
      `arxiv_max_results`, `max_citation_depth`, `min_entity_confidence`, `entity_extraction_max`,
      `depth_multipliers`. `.env.example`: `SEMANTIC_SCHOLAR_API_KEY` (optional).

**Acceptance:** `pa research "retrieval augmented generation" -d 3` populates both graphs and
links them to the interest; `pa graph --kind citation --topic "..."` shows the litmaps-style edges.

### Phase R6 — Cleanup, docs, tests (1 day)

- [ ] Delete `src/store/graph.py` and any imports; confirm nothing references it.
- [ ] Re-sync **SYSTEM_DOCUMENTATION.md** §4.2 (Research Agent), §6 (schema), §10 (status) from
      the shipped code.
- [ ] Full suite: `poetry run pytest tests/ --ignore=tests/test_core.py -v`; `black`/`ruff`/`mypy`.
- [ ] Update memory: Research Agent is now implemented (supersede the "rolled back" note).

---

## 4. Reuse & interest linkage (G6 in practice)

The flow that makes "researching an interest reuses existing knowledge" real:

```
research(topic, interest_id):
  existing = store.get_existing_research(topic, interest_id)   # prior runs, papers, concepts
  if existing.papers:                                          # we already know things
      depth = _decide_depth(...lower if well-covered...)       # don't re-fetch the world
      seed_ids = [p.id for p in existing.papers]               # extend the *existing* graph
  # new papers are merged into the same nodes (idempotent IDs),
  # new edges attach to existing concept/citation nodes,
  # everything links to interest_id → next time, even richer.
```

So the second time you research an interest you don't start from zero: you extend the graph
you already built, and the agent spends its budget on the **frontier**, not re-discovery.

---

## 5. Config (new keys)

```toml
[agents.research]
semantic_scholar_max_results = 12   # seed papers from S2 search
arxiv_max_results            = 6    # supplementary fresh preprints
max_citation_depth           = 2    # citation-graph BFS hops (litmaps frontier)
min_entity_confidence        = 0.6
entity_extraction_max        = 20
# depth → budget multipliers (papers + hops)
depth_shallow = 0.5
depth_normal  = 1.0
depth_deep    = 2.0
```

```bash
# .env (optional but recommended for rate limits)
SEMANTIC_SCHOLAR_API_KEY=...
```

---

## 6. Testing strategy (summary)

| Layer | What to assert | Network |
|---|---|---|
| Store (R1) | idempotent upserts, directed edges, subgraph BFS, reuse query | none |
| Connectors (R2) | normalization, reference/citation parsing | replay fixtures |
| Skills (R3) | confidence filter, closed vocab, JSON tolerance | FakeLLM |
| Agent (R4) | re-run adds 0 dupes, frontier bounded, decisions vary, interest links | FakeLLM + replay |
| Integration (R5) | `pa research` populates both graphs + links; `pa graph` renders | FakeLLM + replay |

Always `poetry run pytest` (pytest-asyncio is venv-only). Exclude `tests/test_core.py`
(network-prone, can hang).

---

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Semantic Scholar rate limits without a key | Backoff + `SEMANTIC_SCHOLAR_API_KEY` support; arXiv fallback; cache by `citation_id`. |
| Citation BFS explosion (deep runs) | `max_citation_depth` + novelty stop + `_worth_chasing`. |
| LLM JSON drift (skills) | Tolerant parsing + schema validation + FakeLLM tests; drop low-confidence. |
| Free-tier LLM weak at relation extraction | Closed relation vocab + confidence floor; relations optional (graph still useful with nodes + cites edges). |
| Migrating a live `knowledge.db` | Additive `ALTER`/`CREATE IF NOT EXISTS`; recreate-and-swap only for the empty `citation_relationships`. |
| Two stores diverging | Delete `src/store/graph.py` in R6; single source of truth. |

---

## 8. Sequencing

```
R1 data model ─▶ R2 connectors ─┬▶ R4 agent ─▶ R5 wiring/CLI ─▶ R6 cleanup/docs
                 R3 skills ──────┘
```

R2 and R3 can proceed in parallel after R1. R4 needs both. R5 needs R4. R6 last.

---

## Changelog
- **1.0.0** (2026-06-23): Initial implementation plan — 6 phases (data model → connectors →
  skills → agent → wiring → cleanup). Semantic Scholar primary + arXiv supplementary; citation
  graph via `citation_relationships`; knowledge graph via `concepts`; interest linkage via
  `interest_citation_links` + `research_runs`; structured-pipeline agent (no native tool-calling).
