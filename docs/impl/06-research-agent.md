---
title: "Implementation: Research Agent"
created: 2026-06-21
updated: 2026-06-21
version: 1.0.0
status: Draft
tags: [implementation, research-agent, citation-graph, knowledge-graph, langgraph]
changelog:
  - version: 1.0.0
    date: 2026-06-21
    changes: >-
      New doc (plans.md v4.0.0). Restores a Research Agent as a full agent —
      triggered by Interest Agent classifications, it researches papers,
      GitHub, Medium, and news, and builds a citation graph and a knowledge
      graph. Re-evaluated against the D4 decide-vs-compute litmus test: unlike
      the earlier "Research Radar" pipeline it replaces, this agent decides
      research depth, source priority, and graph novelty per run.
related:
  - ../personal-assistant.plans.md
  - 04-daily-research-agent.md
  - 05-meta-agent-and-skills.md
  - 03-vector-db-and-storage.md
reference:
  - https://arxiv.org/help/api
  - https://docs.github.com/en/rest
---

> Whenever this documentation file changes, update the `updated` field and append a new entry to `changelog` describing the revision.

# Implementation: Research Agent

> **Why this is an agent, not a pipeline (D4).** A scheduled pull-everything
> connector (what [04-daily-research-agent.md](04-daily-research-agent.md) does for
> *activity* signals) has no branch point — same steps, every run. The Research
> Agent is different: it is **triggered reactively** by an Interest Agent
> classification, and it **decides** (a) how deep to chase a topic — including
> following citation trails across multiple papers, (b) which sources are worth the
> latency for this topic, and (c) what's novel enough to add to the graph versus
> redundant with what's already there. Those are real choices made differently per
> run, which is what earns the agent label per the litmus test in
> [agent.architecture-guide.md §2](../agent.architecture-guide.md#2-the-core-distinction-you-must-internalize-d4).

---

## 1. Trigger & Position in the Flow

```
Interest Agent classification (new or strengthened interest)
        │  ResearchTrigger(topic, reason, strength)
        ▼
                    Research Agent
        ┌─────────────────────────────────────────┐
        │ decide: which sources, how deep, what's  │
        │ novel  →  fetch  →  extract  →  graph     │
        └─────────────────────────────────────────┘
        │                              │
        ▼                              ▼
  Knowledge Base                Graph store
  (chunks, embedded,            (citation graph: paper→paper "cites"
   cited by Brainstorm/          knowledge graph: concept/entity relations)
   Opportunity)                       │
                                       ▼
                              Opportunity Agent (synthesis input)
                              Brainstorming Agent (on-demand deep-dive target)
```

Three ways a run starts:
1. **Automatic** — an `Interest Agent` classification emits a `ResearchTrigger`
   (the common path; see [05-meta-agent-and-skills.md §4](05-meta-agent-and-skills.md#4-the-interest-agent-the-user-model)).
2. **Manual** — `pa research <topic>` / `/research <topic>` (a `ResearchTopic`
   command), for "go look into this now."
3. **Brainstorm handoff** — the Brainstorming Agent, mid-session, decides KB
   coverage is too thin and invokes the Research Agent directly ("research this,
   then propose") — see
   [../personal-assistant.brainstorm-feature.md §9](../personal-assistant.brainstorm-feature.md#9-open-questions),
   resolved by this doc's existence.

---

## 2. The Agent

```python
# src/agents/research.py
class ResearchState(TypedDict):
    topic: str
    reason: str                 # why this topic — from the trigger
    depth: str                  # "shallow" | "normal" | "deep" — decided, not fixed
    sources_tried: list[str]
    papers: list[Paper]
    citation_frontier: list[str]   # paper ids still worth chasing
    findings: ResearchFindings

class ResearchAgent:
    async def run(self, trigger: ResearchTrigger) -> ResearchFindings:
        depth = self._decide_depth(trigger)                     # decision 1
        sources = self._prioritize_sources(trigger.topic, depth) # decision 2
        papers, repos, articles = await self._fetch(trigger.topic, sources)

        graph_delta = GraphDelta()
        frontier = [p.id for p in papers]
        hops = 0
        while frontier and hops < settings.research.max_depth:    # decision 3: keep chasing?
            citations = await self._fetch_citations(frontier)
            new_papers = [c for c in citations if self._is_novel(c, self.graph)]  # decision 4
            graph_delta += await self.skills.citation_graph_construction(new_papers)
            frontier = [p.id for p in new_papers if self._worth_chasing(p, trigger)]
            papers += new_papers
            hops += 1

        entities, edges = await self.skills.entity_relationship_extraction(
            [p.abstract for p in papers] + [a.body for a in repos + articles])
        graph_delta += await self.skills.knowledge_graph_construction(entities, edges,
                                                                       existing_graph=self.graph)
        await self.graph_store.apply(graph_delta)
        chunks = await self._chunk_and_embed(papers, repos, articles)
        await self.kb.upsert(chunks)
        return ResearchFindings(topic=trigger.topic, graph_delta=graph_delta, chunks=chunks)
```

The four marked decision points are exactly what make this an agent rather than the
pipeline in [impl/04](04-daily-research-agent.md):

| Decision | Based on | Example |
|----------|----------|---------|
| **Depth** (`shallow`/`normal`/`deep`) | trigger strength/reason, prior research on this topic | a brand-new strong interest → `deep`; a minor reinforcement → `shallow` or skip |
| **Source priority** | topic shape | a CS-theory topic weights arXiv heavily; a tooling topic weights GitHub + Medium |
| **Whether to keep chasing citations** | citation frontier size, `max_depth`, diminishing novelty | stop early if the last hop added nothing new to the graph |
| **Novelty** (`_is_novel`) | similarity to existing graph nodes (Knowledge Graph Construction's dedup step) | a paper already in the graph from a prior run isn't re-added, just re-weighted |

---

## 3. Source Connectors (`src/research/connectors/`)

Distinct from the **activity** connectors in [impl/04](04-daily-research-agent.md)
— same `Connector.fetch` shape, different package, different caller (the Research
Agent, not the scheduled sensing pipeline), different trigger (targeted by topic,
not a timer).

```python
# src/research/connectors/base.py
class ResearchConnector(Protocol):
    async def fetch(self, topic: str, *, depth: str) -> list[RawDoc]: ...
```

| Connector | File | Returns | Notes |
|-----------|------|---------|-------|
| arXiv | `connectors/arxiv.py` | papers (abstract + references list) | **Build first** — the references list is what seeds the citation frontier. |
| GitHub (trending/relevant) | `connectors/github_research.py` | repos matching topic | Distinct from the *activity* GitHub connector in impl/04 (your own repos) — same API, different query shape (topic search, not `user:`). |
| Medium | `connectors/medium.py` | articles | No clean public API; RSS-per-publication or a scraping fallback. Treat content as lower-authority than arXiv/GitHub in ranking. |
| News | `connectors/news.py` | articles | A news API or curated RSS aggregator; same shape as Medium. |

`_prioritize_sources` (§2) decides which of these to call and in what order for a
given topic — not every run hits every source.

---

## 4. Citation Graph vs Knowledge Graph

Two distinct graph **skills** (registered once, in
[05-meta-agent-and-skills.md §6](05-meta-agent-and-skills.md#6-the-skill-registry-implementation),
not duplicated here), both used only by this agent today:

| | Citation Graph | Knowledge Graph |
|---|---|---|
| Nodes | papers | concepts / entities |
| Edges | `cites` (paper → paper) | typed relations (`uses`, `extends`, `competes_with`, …) |
| Built from | a paper's reference list | Entity & Relationship Extraction over abstracts/articles/repo READMEs |
| Answers | "what does this paper build on / get cited by?" | "how does concept X relate to concept Y across everything I've researched?" |
| Consumed by | Opportunity Agent (novelty/gap signals), Brainstorming Agent (citation-trail answers) | Opportunity Agent (concept synthesis input), Brainstorming Agent (concept questions) |

Both are stored as node/edge tables in the graph store — see
[03-vector-db-and-storage.md §3](03-vector-db-and-storage.md#3-graph-store--citation-graph--knowledge-graph)
for the schema.

---

## 5. Output: `ResearchFindings`

```python
@dataclass
class ResearchFindings:
    topic: str
    graph_delta: GraphDelta       # nodes/edges added this run, for both graphs
    chunks: list[Chunk]           # newly embedded KB content (provenance: connector, topic)
    summary: str                  # cited one-paragraph "what's new" (Summarization skill)
```

This is what the Interest→Research→Opportunity bridge in
[plans.md → Loops & Triggers](../personal-assistant.plans.md#loops--triggers) hands
forward: the Opportunity Agent reads `graph_delta` + the KB; the insight digest
surfaces `summary`; the Brainstorming Agent can cite specific graph nodes in an
answer.

---

## 6. Testing

- **Decision points:** fixture triggers with varying strength/reason → assert depth
  and source-priority choices differ accordingly (not the same every time — that
  would indicate it's regressed to a pipeline).
- **Citation chasing:** a fixture paper graph with a known citation chain → assert
  the frontier expands up to `max_depth` and stops on diminishing novelty.
- **Novelty/dedup:** re-run the same topic twice → second run adds no duplicate
  graph nodes, only weight/confidence updates.
- **Graph correctness:** assert citation edges are directed (`cites`, not
  symmetric) and knowledge-graph relation types are from a closed vocabulary.
- **Connector fixtures:** record/replay (VCR-style) per connector, same pattern as
  [impl/04 §5](04-daily-research-agent.md#5-testing).

---

## Related
- [04-daily-research-agent.md](04-daily-research-agent.md) — the activity sensing pipeline (not this agent)
- [05-meta-agent-and-skills.md](05-meta-agent-and-skills.md) — Interest Agent (the trigger source), Opportunity Agent (a consumer), the shared Skill registry
- [03-vector-db-and-storage.md](03-vector-db-and-storage.md) — graph store + KB schema
- [../personal-assistant.brainstorm-feature.md](../personal-assistant.brainstorm-feature.md) — Brainstorming Agent's on-demand handoff into this agent
- [../agent.architecture-guide.md](../agent.architecture-guide.md) — the decide-vs-compute litmus test this agent is held to
