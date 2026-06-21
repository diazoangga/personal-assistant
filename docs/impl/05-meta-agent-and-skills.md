---
title: "Implementation: Meta, Interest & Opportunity Agents + Skills"
created: 2026-06-20
updated: 2026-06-21
version: 3.0.0
status: Draft
tags: [implementation, meta-agent, interest-agent, opportunity-agent, langgraph, skills]
changelog:
  - version: 1.0.0
    date: 2026-06-20
    changes: "Initial Meta-Agent + Research/Architect/Developer worker chain (SDLC builder)"
  - version: 2.0.0
    date: 2026-06-21
    changes: >-
      Rewritten for the cognitive-engine paradigm. Replaced the worker chain with
      three cognitive agents (Meta, Interest, Opportunity), the canonical Skill
      registry, and the loop graphs. Removed Build/Architect/Developer.
  - version: 3.0.0
    date: 2026-06-21
    changes: >-
      Split out of a 3-agent doc into one of three (plans.md v4.0.0, five agents
      total). Moved Brainstorm out — it's now a full agent with its own doc
      ([../personal-assistant.brainstorm-feature.md](../personal-assistant.brainstorm-feature.md)).
      Moved Research out to its own doc ([06-research-agent.md](06-research-agent.md))
      — Interest Agent now documents *triggering* it rather than absorbing it.
      Added the Meta Agent's self-modification authority (D6) with the concrete
      human-review workflow. Retitled the file to reflect its narrower scope
      (filename kept as `05-` to preserve cross-links).
related:
  - ../personal-assistant.plans.md
  - 01-cli-and-core-engine.md
  - 06-research-agent.md
reference:
  - https://github.com/langchain-ai/langgraph
---

> Whenever this documentation file changes, update the `updated` field and append a new entry to `changelog` describing the revision.

# Implementation: Meta, Interest & Opportunity Agents + Skills

This doc implements three of the system's five agents — **Meta**, **Interest**, and
**Opportunity** — plus the **skills they compute with** and the LangGraph graph that
ties them together. The other two agents, **Research** and **Brainstorming**, have
their own docs ([06-research-agent.md](06-research-agent.md) and
[../personal-assistant.brainstorm-feature.md](../personal-assistant.brainstorm-feature.md))
because each owns enough unique machinery (multi-source connectors + graph
construction; web search + multi-turn session state) to warrant it. All five share
the same Skill registry below and the same Agent/Skill/Tool separation (D4) from
[plans.md](../personal-assistant.plans.md).

> **The rule, restated:** Agents decide, Skills compute, Tools execute. Five things
> in this system genuinely *choose among actions over time*: Meta, Interest,
> Research, Opportunity, Brainstorming. Everything else is a skill or a tool.

---

## 1. Agents at a glance (this doc's three)

| Agent | Goal | Reads | Produces | Skills it uses |
|-------|------|-------|----------|----------------|
| **Meta** | keep a high-level model of what's happening; run the right loop; learn; propose self-improvements | events, profile, feedback, agent metrics, run traces | activity classification, orchestration decisions, **reviewable improvement proposals** | Classification, Memory Retrieval |
| **Interest** | model the user's evolving interests; decide when a classification is worth triggering deeper research | signals (activity sensing), prior interest graph | updated interest graph, profile, timeline, **Research Agent triggers** | Topic Extraction, Clustering, Trend Detection |
| **Opportunity** | turn research + interest into ranked, evidence-backed proposals scoped to a stated problem | Research Agent's graphs + KB, interest graph, memory | opportunities (ideas/research/learning), with citations | Hybrid Retrieval, Query Reformulation, Gap Analysis, Concept Expansion, Concept Synthesis, Recommendation Ranking, Summarization |

For the full five-agent picture (incl. Research and Brainstorming) see
[plans.md → High-Level Architecture](../personal-assistant.plans.md#high-level-architecture).

---

## 2. The Meta Agent (orchestrator + brain)

The Meta Agent does **not** extract topics, research papers, or rank ideas itself.
It decides *which loop or agent runs*, *what the user is currently doing*, *whether
past output was good*, and — per **D6** — *what change to propose* when performance
is weak. It runs as a LangGraph state machine on the small/fast `meta` role.

```
                  ┌──────────────────────────────────────────────────┐
   trigger ─────► │                  meta (router)                  │
  (loop tick /    │  classify activity · pick next action ·         │
   command /      │  read memory · evaluate feedback · review perf  │
   feedback)      └───┬───────────┬────────────┬───────────┬────────┘
                      ▼           ▼            ▼           ▼
               ┌───────────┐ ┌──────────┐ ┌───────────┐ ┌─────────────┐
               │ Interest  │ │ Research │ │Opportunity│ │ Brainstorm  │
               │  Agent    │ │  Agent   │ │  Agent    │ │  session    │
               └───────────┘ └──────────┘ └───────────┘ └─────────────┘
```

```python
# src/agents/meta/graph.py
class MetaState(TypedDict):
    trigger: str               # "loop:sense" | "loop:understand" | "cmd:ask" | "review:weekly" | ...
    user: str
    activity: str | None       # work | research | personal-project | learning | exploration
    decision: str | None       # which agent/loop to run next
    payload: dict

def build_meta_graph(agents, skills, tools, publish):
    g = StateGraph(MetaState)
    g.add_node("meta", meta_router(skills, tools, publish))
    g.add_node("interest", run_interest(agents.interest, publish))
    g.add_node("research", run_research(agents.research, publish))
    g.add_node("opportunity", run_opportunity(agents.opportunity, publish))
    g.add_node("propose", propose_self_modification(skills, tools, publish))  # D6
    g.set_entry_point("meta")
    g.add_conditional_edges("meta", route_next, {
        "interest": "interest", "research": "research", "opportunity": "opportunity",
        "propose": "propose", "done": END,
    })
    g.add_edge("interest", "meta")
    g.add_edge("research", "meta")
    g.add_edge("opportunity", "meta")
    g.add_edge("propose", END)        # a proposal always ends the run — it waits for review
    return g.compile(checkpointer=sqlite_checkpointer())
```

### Responsibilities
- **Activity classification.** On signal/command, run the Classification skill over
  recent signals → `work | research | personal-project | learning | exploration`.
  Stored as activity context; answers success-metric #2.
- **Orchestration.** Decide which loop/agent runs given the trigger and current
  state — including routing an Interest classification into a **Research Agent**
  trigger (see [06-research-agent.md](06-research-agent.md) §1).
- **Feedback loop.** When a `Feedback` command arrives (or an opportunity is
  saved/dismissed), update per-agent acceptance/correction rates in memory.
- **Performance review → self-modification proposals (D6).** Periodically (or on
  request), Meta reviews accumulated `run_traces` and per-agent metrics, and may
  *propose* a change to a skill, a prompt, or a tool wiring. See §3.

### Authority

| | |
|---|---|
| **Can** | trigger any agent, prioritize loops, request more analysis, evaluate agent performance, **draft** a skill/prompt edit or a new/changed tool wiring |
| **Cannot** | modify source signals directly, **apply any skill/prompt/tool change without human review** |

> **D6 is load-bearing, not a suggestion.** "Meta can change the skills, prompt, or
> add tools" describes Meta's *authority to decide what should change* — it does
> not describe Meta *applying* that change unsupervised. The distinction matters:
> deciding is exactly what makes Meta an agent; auto-applying is a separate,
> higher-risk capability the system does not grant it.

---

## 3. Self-Modification Proposals (D6 — the concrete workflow)

This is the mechanism behind the "human-reviewed" line in §2's authority table.

```
run_traces + per-agent acceptance/correction rates  (accumulated continuously)
        │
        ▼
Meta Agent performance review (scheduled, e.g. weekly, or on-demand via `pa review run`)
        │
        ▼
weak-agent / weak-skill detection
   e.g. "Opportunity's ranking ignores recency"; "Brainstorm web-search fallback
   triggers too rarely — KB-thin sessions are getting weak inquiry answers"
        │
        ▼
Meta drafts a PROPOSAL — not a change:
   { target: skill | prompt | tool_wiring,
     diff: <concrete patch>,
     evidence: [run_trace ids, metric deltas],
     rationale: <why this fixes the weak point> }
        │
        ▼
 ⏸ Written to a reviewable surface (Git diff / PR, or a `proposals` table
   surfaced via `pa review list` / a Slack approval message) — NEVER applied
   directly to the running skill, prompt, or tool registry.
        │
        ▼
You: approve · edit · reject
        │
        ▼
Only an APPROVED proposal is merged. The approve/reject/edit outcome is itself
recorded — feedback on whether Meta's proposals are getting better over time.
```

```python
# src/agents/meta/tools.py
@dataclass
class SelfModProposal:
    id: str
    target: str          # "skill:gap_analysis" | "prompt:opportunity.synthesis" | "tool:web_search"
    diff: str            # unified diff against the current file/prompt/config
    evidence: list[str]  # run_trace ids / metric snapshots
    rationale: str
    state: str = "pending"   # pending | approved | rejected | edited_then_approved

async def propose_self_modification(skills, tools, publish):
    async def node(state: MetaState) -> MetaState:
        weak = await detect_weak_points(memory.agent_metrics(), memory.run_traces())
        if not weak:
            return state
        proposal = await draft_proposal(weak, llm_role="meta")
        memory.save_proposal(proposal)                      # state="pending"
        await publish(Progress(state["job_id"], phase="propose",
                               message=f"proposal {proposal.id} awaiting review"))
        return state
    return node
```

`pa review list` / `pa review show <id>` / `pa review approve|reject <id>` (and a
Slack twin with approve/reject buttons) are the only paths from `pending` to
`approved`. Nothing else writes to the live skill/prompt/tool registry on Meta's
behalf.

---

## 4. The Interest Agent (the user model)

The hardest modeling problem in the system. It consumes signals from the activity
sensing pipeline ([04-daily-research-agent.md](04-daily-research-agent.md)) and
maintains the interest graph and profile — and it is the **trigger** for the
Research Agent.

```python
# src/agents/interest.py
class InterestAgent:
    async def update(self, signals: list[Signal]) -> InterestGraphDelta:
        topics = await self.skills.topic_extraction(signals)        # concepts/tags
        clusters = await self.skills.clustering(topics)             # new or existing category
        trend = await self.skills.trend_detection(clusters, self.history)
        # trend → strength↑/↓, emerging, abandoned, decay
        delta = self.graph.apply(clusters, trend)
        for topic in delta.new_or_strengthened:
            await self.bus.publish(ResearchTrigger(topic=topic, reason=delta.reason(topic)))
        return delta
```

Decisions it owns (why it's an agent, not a pipeline):
- **What counts as an interest** vs noise (threshold + persistence over time).
- **Classification: new category or existing?** Every incoming topic is matched
  against the existing taxonomy (Clustering skill) before a new node is created —
  this is what keeps the interest graph from fragmenting into near-duplicate nodes.
- **How strength evolves** (reinforcement on repeat signals; **decay** when absent).
- **Emerging vs abandoned** detection (Trend Detection skill output → graph state).
- **Whether a classification is worth triggering the Research Agent** — not every
  signal warrants deep research; new-or-strengthened interests do, routine
  reinforcement of a stable interest usually doesn't.

Outputs: the **interest graph** (nodes = topics, edges = relationships, weights =
strength), an **interest timeline**, the long-term **user profile**, and
**Research Agent triggers**. Stored in Persistent Memory — see
[03-vector-db-and-storage.md](03-vector-db-and-storage.md) §2.

> This is where to prototype against *real* data early. If the interest model is
> wrong, every downstream Research Agent run and every Opportunity recommendation
> is wrong.

---

## 5. The Opportunity Agent (the value producer)

The primary value producer. Synthesizes evidence-backed proposals from the
**Research Agent's graphs + KB** + interest graph + memory, scoped to the user's
**current problem or issue**. **Gap Analysis and Serendipity are skills here, not
separate agents.**

```python
# src/agents/opportunity.py
class OpportunityAgent:
    async def scan(self, focus: str | None = None) -> list[Opportunity]:
        interests = self.memory.top_interests()
        graphs    = self.graph_store.relevant_subgraphs(interests, focus)  # citation + knowledge graph
        gaps      = await self.skills.gap_analysis(interests, landscape=graphs)
        seeds     = await self.skills.concept_expansion(interests)     # serendipity
        context   = await self.skills.hybrid_retrieval(self._queries(interests, gaps, seeds, focus))
        ideas     = await self.skills.concept_synthesis(interests, context, graphs)
        ranked    = await self.skills.recommendation_ranking(ideas + gaps + seeds)
        return [self._with_provenance(o, context, graphs) for o in ranked]    # "why this"
```

`focus` is the **current problem or issue** the user is asking about — set
explicitly (`pa opportunities --focus "stuck on X"`) or inferred from the Meta
Agent's current activity classification. Every `Opportunity` carries the
**interest signals**, **KB sources**, and **graph nodes** it was built from — that
provenance is the answer to success-metric #8 ("why are you recommending this?").
An opportunity can be **saved** (promoted to a tracked item) or **dismissed** (a
negative feedback signal the Meta Agent records).

### The Insight Digest & proactive alerts

The Opportunity Agent also produces the **proactive insight digest** — this used to
live in the activity-sensing pipeline doc, but it now synthesizes across the
**Research Agent's** fresh findings (not just raw activity), so it belongs here.

```python
# src/agents/opportunity.py (cont.)
async def build_digest(self, findings: list[ResearchFindings], interests: InterestGraph) -> Digest:
    sections = [DigestSection(i.name, await self.skills.recommendation_ranking(
                    self._candidates(findings, i), k=4)) for i in interests.top()]
    sections.append(DigestSection("Adjacent — worth a look",
                                  await self.skills.concept_expansion(interests.top())))
    return Digest(date=today(), sections=sections)
```

Delivery is interface-symmetric (built once by the engine, rendered by whichever
interface asks): Slack Block Kit → `#assistant`; CLI → `pa digest [date]`. Beyond the
scheduled digest, a strong hit (a Research Agent run that adds an unusually
high-novelty graph node) can trigger a rate-limited proactive alert — same delivery
path, just unscheduled (Phase 3).

---

## 6. The Skill Registry (implementation)

Skills are pure-ish transforms in `src/skills/`. They may call tools (LLM, vector,
memory, graph store) but hold no goal and no cross-call state. Canonical list (one
name each — the full registry, including the skills Research and Brainstorming use,
lives here since it's shared):

```python
# src/skills/  — signatures (illustrative)
async def classification(items, *, kind, llm) -> str | list[str]   # activity/content/intent
async def topic_extraction(texts, *, llm) -> list[Topic]
async def entity_relationship_extraction(text, *, llm) -> tuple[list[Entity], list[Edge]]
async def citation_graph_construction(papers, *, llm) -> GraphDelta   # paper → paper "cites"
async def knowledge_graph_construction(entities, edges, *, existing_graph) -> GraphDelta
async def clustering(topics) -> Taxonomy
async def trend_detection(series, history) -> TrendReport            # emerging/abandoned/strength
async def summarization(texts, *, cited=False, llm) -> str           # cited variant for answers
async def memory_retrieval(query, *, memory) -> list[MemoryHit]
async def hybrid_retrieval(query, *, vector, k=8) -> list[Hit]       # dense+sparse+rerank
async def query_reformulation(question, *, llm, max_hops=3) -> list[str]
async def recommendation_ranking(candidates) -> list[Scored]
async def gap_analysis(interests, *, landscape) -> list[Gap]
async def concept_expansion(interests, *, llm) -> list[Concept]      # serendipity
async def concept_synthesis(interests, context, *, llm) -> list[Idea]
```

> **Reuse, don't fork.** Topic Extraction is called by Interest, Research, and
> Opportunity — one implementation. Citation/Knowledge Graph Construction are used
> only by Research today, but they're registered here, not duplicated into
> [06-research-agent.md](06-research-agent.md), because the rule is one
> implementation per capability regardless of which doc *describes* its usage. If
> you need "Relevance Ranking", you mean Recommendation Ranking; reuse it. The
> registry is the
> [reuse contract](../agent.architecture-guide.md#4-the-skill-registry-is-the-reuse-contract).

### Orchestration skills (Markdown templates)
Some loops follow a fixed procedure better expressed as a template the Meta Agent
loads than as free-form reasoning. These live in `~/assistant/skills/` (seed copies
in repo `skills/`), Git-tracked, with sections **Trigger / Steps / Success Criteria
/ Failure Handling**.

```markdown
# Skill: opportunity-scan

## Trigger
Insight tick, or a `brainstorm` ideation turn.

## Steps
1. memory.top_interests()
2. graph_store.relevant_subgraphs(interests, focus)
3. gap_analysis(interests, landscape=graphs)
4. concept_expansion(interests)            # serendipity seeds
5. hybrid_retrieval(queries from 1–4)
6. concept_synthesis(interests, context, graphs)
7. recommendation_ranking(all candidates)
8. attach provenance (interest signals + KB sources + graph nodes) to each

## Success Criteria
- Every opportunity cites ≥1 interest signal AND ≥1 KB/graph source
- Top-ranked items are not duplicates of dismissed opportunities

## Failure Handling
- Thin KB/interest/graph → return fewer, lower-confidence items flagged "cold-start"
- No synthesis → fall back to gap-based learning recommendations
```

```python
# src/skills/loader.py
def load_orchestration_skills() -> dict[str, str]:
    return {p.stem: p.read_text() for p in Path("~/assistant/skills").expanduser().glob("*.md")}
```

Self-modification proposals (§3) that target an orchestration skill land here as a
diff to one of these Markdown files — Git-tracked, reviewed like any other change.

---

## 7. Why LangGraph (recap)

We need conditional edges (route by trigger/intent/agent), a checkpointer (replay a
reasoning run; resume a brainstorm session), and human-in-the-loop interrupts
(feedback gates **and** self-modification approval gates). LangGraph gives all
three; a role-based crew framework does not.

---

## 8. Testing

- **Routing:** stub agents; assert the Meta graph routes each trigger correctly,
  including routing an Interest classification into a Research Agent trigger.
- **Skills:** pure transforms — unit-test directly with fixtures (the bulk of tests).
- **Interest model:** feed a signal timeline; assert strength rises on repeats and
  decays on absence; assert emerging/abandoned detection; assert a new-or-strong
  classification emits a `ResearchTrigger`.
- **Provenance:** assert every Opportunity carries source/signal/graph-node IDs
  (fail the test if any claim is uncited).
- **Self-modification gate:** assert `propose_self_modification` never writes to
  the live skill/prompt/tool registry — only to the `proposals` table; assert
  `pa review approve` is the only code path that does.
- **Cold-start:** thin KB/interest/graph → assert graceful degradation, not a crash.

---

## Related
- [01-cli-and-core-engine.md](01-cli-and-core-engine.md) — engine, events, sessions
- [03-vector-db-and-storage.md](03-vector-db-and-storage.md) — interest graph, opportunities, retrieval, graph store
- [04-daily-research-agent.md](04-daily-research-agent.md) — activity signals the Interest Agent consumes
- [06-research-agent.md](06-research-agent.md) — the agent Interest Agent triggers
- [../personal-assistant.brainstorm-feature.md](../personal-assistant.brainstorm-feature.md) — Brainstorming Agent
- [../agent.architecture-guide.md](../agent.architecture-guide.md) — adding agents/skills
