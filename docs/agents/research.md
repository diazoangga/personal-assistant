# Research Agent

Given a topic, builds two linked graphs — a **citation graph** (papers and who-cites-whom)
and a **concept knowledge graph** (entities and how they relate) — wires both to the
originating interest, and writes a run record. Triggered autonomously by the Interest Agent
or manually via `ResearchTopic` / `pa research`.

## The 8-step pipeline

`research(topic, *, interest_id?, depth?, trigger_source="manual", publish?, job_id?)`

| # | Step | What happens |
|---|---|---|
| 1 | **REUSE** | `get_existing_research(topic, interest_id)` → set of papers already known, so we only enrich what's new. |
| 2 | **SEED** | Decide depth (`_decide_depth`), pick sources (`_prioritize_sources`), search **Semantic Scholar** (→ **OpenAlex** fallback if empty/rate-limited) and **arXiv** for theory topics. Each raw paper is upserted as a citation. |
| 3 | **EXPAND** | For `normal`/`deep`, BFS the citation frontier — follow references **and** citations (`semantic_scholar.get_references`/`get_citations`), novelty-gated by `_worth_chasing`, to `max_citation_depth` (1 for normal, up to config for deep). |
| 4 | **ENRICH** | For each *new* paper, `synthesize_paper` (LLM) writes a `conclusion` + `notes`; stored via `update_citation_notes`. |
| 5 | **EXTRACT** | `extract_entities` mines concepts from abstracts; `extract_relations` mines typed edges between them → `concepts` + `concept_relationships`. |
| 6 | **LINK** | Bidirectional edges: interest↔citation, citation↔concept, interest↔concept. |
| 7 | **PERSIST** | `finish_research_run` records deltas (`papers_new`, `concepts_new`, status). |
| 8 | **SUMMARIZE** | `summarize_run` (LLM) writes a "what's new" paragraph over the new papers + concepts. |

Returns `ResearchResult(topic, new_papers, new_concepts, new_edges, summary, run_id)`.

## Depth

| Depth | Expansion | When |
|---|---|---|
| `shallow` | none (seed only) | lots of existing research, or weak reinforcement |
| `normal` | 1 hop | default |
| `deep` | up to `max_citation_depth` hops | strong new interest (strength ≥ 0.7, little existing) |

`_decide_depth` picks automatically when the caller doesn't override; the Interest Agent
passes `deep` for high-strength triggers.

## Sources & connectors

`tools/` holds the connectors, each returning `RawPaper` objects with `to_citation_dict()`:

| Connector | Role |
|---|---|
| `semantic_scholar.py` | Primary: search + `get_references` + `get_citations` (citation graph). |
| `openalex_connector.py` | Free, no rate limits — fallback when Semantic Scholar returns nothing. |
| `arxiv_connector.py` | Supplementary open-access papers, weighted for theory topics. |

Novelty gate (`_worth_chasing`): stop expanding a large frontier at depth, drop
zero-citation papers.

## Skills

`skills/` holds the LLM operations: `paper_synthesis.py` (conclusion + notes),
`entity_extraction.py` (concepts, filtered by `min_entity_confidence`, default 0.6),
`relation_extraction.py` (typed weighted edges), `summarization.py` (run summary).

## Idempotency

Citations and concepts are content-addressed (`compute_citation_id`, `compute_concept_id`)
and upserted, so re-running a topic enriches rather than duplicates. `UNIQUE` edge
constraints make link insertion idempotent too.

## Config knobs

`semantic_scholar_max_results` (20), `arxiv_max_results` (10), `max_citation_depth` (2),
`min_entity_confidence` (0.6), `entity_extraction_max` (20).

## Gotchas

- **Citation depth is exponential** in API calls — test shallow first.
- **Entity confidence** trades noise vs recall around 0.6.
- **Semantic Scholar rate limits** are real; the OpenAlex fallback is intentional, not a
  bug.

---

> **Source of truth:** `src/agents/research/agent.py`, `src/agents/research/tools/`,
> `src/agents/research/skills/`, `src/store/knowledge.py`. Schema:
> [storage/knowledge-store.md](../storage/knowledge-store.md).
