---
title: "Brainstorming Agent — Interactive Inquiry & Ideation"
created: 2026-06-21
updated: 2026-06-21
version: 0.2.0
status: Draft
tags:
  - explanation
changelog:
  - version: 0.1.0
    date: 2026-06-21
    changes: "Initial RFC/feature design for the Brainstorm conversational mode (inquiry + ideation), targeting the cognitive-engine paradigm."
  - version: 0.2.0
    date: 2026-06-21
    changes: >-
      Promoted Brainstorm from "a mode of the Meta Agent" to the **Brainstorming
      Agent** — a full agent in the 5-agent model (plans.md v4.0.0), per the D4
      litmus test: it decides KB-vs-web-vs-Research-handoff per turn, which is a
      real branch point, not a fixed transform. Added **Web Search** as a new
      tool. Resolved open question #2 (session-triggered research) by
      cross-referencing the Research Agent handoff specified in
      [impl/06-research-agent.md](impl/06-research-agent.md). Updated §2's
      architecture table and diagram to the 5-agent model.
audience: Solo developer building a local AI personal assistant (cognitive-engine paradigm)
reference:
  - https://github.com/langchain-ai/langgraph
  - https://qdrant.tech
---

> Whenever this documentation file changes, update the `updated` field and append a new entry to `changelog` describing the revision.

# Brainstorming Agent — Interactive Inquiry & Ideation

> **Paradigm note.** This feature assumes the **cognitive-engine paradigm** — a
> continuous engine that observes the user, models their interests, accumulates
> research, and proactively produces insights — *not* the older SDLC
> project-builder described in
> [personal-assistant.plans.md](personal-assistant.plans.md). This doc uses the
> current **5-agent** model (Meta / Interest / Research / Opportunity /
> Brainstorming) summarized in §2.

---

## Summary

**Brainstorming is a full agent** — one of the five in the cognitive engine,
alongside Meta, Interest, Research, and Opportunity (see
[agent.architecture-guide.md §3](agent.architecture-guide.md#3-the-five-agents-and-what-each-owns)).
It opens a session in which the user can, over one conversation, do three distinct
things against everything the engine has accumulated:

1. **Inquiry** — *"What does my research actually say about X?"* Conversational RAG
   over the full knowledge base, **strictly grounded**: every claim is cited, and
   the answer says *"that isn't in your research"* rather than inventing one.
2. **Ideation** — *"From my research and my interests, what should I build / explore
   next?"* Routes to the **Opportunity Agent**, **loosely grounded**: creative leaps
   are allowed, but every proposed idea must trace back to specific research items
   **and** specific interest signals (the "why am I recommending this" requirement).
3. **Research hand-off** — *"I don't know enough about this yet — go find out, then
   propose."* When the agent decides KB coverage is too thin for either branch
   above, it invokes the **Research Agent** directly (see
   [impl/06-research-agent.md §1](impl/06-research-agent.md#1-trigger--position-in-the-flow))
   rather than answering on a weak basis.

Each user turn is intent-classified and routed independently, so a single session
can fluidly move between "remind me what I read," "now turn that into an idea," and
"go look that up first." Brainstorming reuses the Interest profile, the knowledge
base, and the Opportunity Agent that the rest of the engine already maintains, and
owns one new tool — **Web Search** — for turns the local KB can't ground at all (see
§4).

> **Why this is now an agent, not a Meta Agent mode (D4).** The original design
> reasoned that Brainstorm's per-turn branching "belonged to" the Meta Agent because
> it already lived inside Meta's loop. Re-examined against the litmus test — *does
> it decide, or does it compute?* — the per-turn choice of **KB-only vs. web search
> vs. handing off to the Research Agent** is a real, recurring decision with no
> fixed answer, made differently depending on what's already grounded and what
> isn't. That earns the agent label on its own, independent of Meta. Promoting it
> also simplifies Meta: Meta no longer needs a special-cased "session mode" inside
> its own loop.

---

## Problem Statement

The cognitive engine accumulates a great deal of value, but today that value is
locked behind a one-way, scheduled surface. Three frictions:

1. **Retrieval friction.** Research is *ingested* but not *queryable on demand*. The
   user can read a digest when it arrives, but cannot later ask *"what did I collect
   about local embedding models?"* and get a grounded, cited answer.
2. **Idea latency.** Insights and recommendations only surface inside scheduled
   digests. There is no way to sit down and say *"given everything you know about
   me and what I've read, what should I do next?"* — on demand, interactively.
3. **No interactive loop.** Following up — *"expand on that second one"*, *"make it
   more technical"*, *"combine it with my Rust work"* — is impossible against a
   static digest. Ideas can't be refined in conversation, so they can't be trusted
   or acted on.

Brainstorm closes all three: it makes the accumulated research **conversationally
queryable**, makes ideation **on-demand and refinable**, and gives both a path back
into the engine's feedback loop (see §6).

---

## 2. Where it sits in the architecture

The **Brainstorming Agent** owns its own session loop. Within a session, **each user
turn is intent-classified and routed** to one of three branches — it no longer
borrows the Meta Agent's loop to do this.

The current 5-agent cognitive-engine architecture it plugs into:

| Component | Kind | Role | Brainstorming Agent uses it for |
|-----------|------|------|------------------------|
| **Brainstorming Agent** | Agent (decides) | Hosts the session; classifies & routes each turn (KB / web / Research hand-off) | This doc's subject |
| **Meta Agent** | Agent (decides) | Supervises & performance-reviews the whole system; proposes skill/prompt/tool changes (D6, always human-reviewed) | Receives the accepted-idea feedback signal (§6); may eventually tune Brainstorming's own prompts via a reviewed proposal |
| **Interest Agent** | Agent (decides) | Models the user (interest strength/decay, emerging/abandoned topics) | The "my intention/interest" grounding source for ideation |
| **Research Agent** | Agent (decides) | Researches papers/GitHub/Medium/news on a topic; builds the citation + knowledge graph | Invoked directly by the Research hand-off branch (§3) |
| **Opportunity Agent** | Agent (decides) | Synthesizes ideas/recommendations (gap analysis + serendipity as *skills*) | The ideation branch's value producer |
| Activity sensing pipeline | Supporting (scheduled) | Turns activity into the Interest Agent's feed | Indirect — shapes the Interest profile Brainstorming reads |
| Memory + Graph store | Tool (SQLite + Qdrant) | Long-term memory, vectors, citation/knowledge graph | Hybrid retrieval; graph lookups; where saved ideas land (§6) |
| Memory Retrieval | Skill | Grounded fetch over the memory store | The inquiry branch's retrieval step |
| **Web Search** | 🆕 Tool | External search for turns the KB can't ground | The fallback grounding source before resorting to a full Research Agent hand-off (§4) |
| Skill registry | Supporting | Shared, versioned skills | Resolves the skills in §4 |

```
You
 │  "what did I read about X?" / "what should I build next?" / "look into Y for me"
 ▼
┌────────────────────────────────────────────────────────────────────────────┐
│  BRAINSTORMING AGENT — session  (multi-turn; holds chat history)            │
│                                                                              │
│   per turn ─► [ intent-classify ]  (reuses Classification skill)            │
│                     │                                                       │
│      ┌──────────────┼───────────────────┐                                  │
│      ▼ INQUIRY       ▼ IDEATION           ▼ RESEARCH HAND-OFF               │
│ ┌─────────────┐ ┌──────────────────┐ ┌───────────────────────────┐         │
│ │ Memory      │ │ Opportunity Agent │ │ decide: KB too thin?      │         │
│ │ Retrieval   │ │ (gap analysis,    │ │  → Web Search tool        │         │
│ │ + KB hybrid │ │  concept expansion,│ │    (quick), or            │         │
│ │ query, or   │ │  ranking) seeded  │ │  → ResearchTopic command   │         │
│ │ Web Search  │ │  by Interest + KB │ │    to the Research Agent   │         │
│ │ if KB empty │ │                   │ │    ("research this, then   │         │
│ │             │ │                   │ │    propose")               │         │
│ └──────┬──────┘ └─────────┬─────────┘ └─────────────┬──────────────┘         │
│        ▼ STRICT grounding ▼ LOOSE grounding          ▼ on completion:        │
│  cited answer, or   proposed ideas, each traced to    re-enter INQUIRY/      │
│  "not in your       research items + interest signals  IDEATION with the     │
│  research"                                              new findings         │
└────────────────────────────────────────────────────────────────────────────┘
                     │  optional: `save idea`
                     ▼
            Opportunity record in Memory store  ──► Meta Agent feedback loop
```

**Key point:** all three branches reuse machinery that already exists elsewhere.
Inquiry reuses **Memory Retrieval + KB** (falling back to Web Search); ideation
reuses the **Interest profile + KB + Opportunity Agent**; the Research hand-off
reuses the **Research Agent** wholesale via the same `ResearchTopic` command a
manual `/research` invokes. The Brainstorming Agent's own footprint is the session
loop, the per-turn routing decision, and the Web Search tool.

> **Design principle (upheld throughout): `Agent = Why, Skill = How, Tool = With What`.**
> Litmus test for an agent: *does it decide (choose among actions over time) or
> merely compute (pure transform)?* Skills compute; agents decide; tools execute
> external actions. The Brainstorming Agent **decides which of three branches a
> turn takes, including whether the KB is trustworthy enough to skip an external
> lookup** — a real, recurring decision, which is why it now stands on its own
> rather than borrowing Meta's loop (see the Summary's callout). The genuinely new
> *computation* (query reformulation, cited synthesis) still lands as **skills**,
> not agents — promoting the agent didn't change that part.

---

## 3. Two grounded intents, plus a hand-off

The session's power is that the *same conversation* supports two intents with two
deliberately different grounding contracts. Misclassifying the grounding mode is the
core risk, so the contracts are explicit:

| | **Inquiry** | **Ideation** |
|---|-------------|--------------|
| User question shape | "What does my research say about X?" / "Have I read anything on Y?" | "What should I build next?" / "Propose an idea from this." |
| Routed to | Memory Retrieval skill + KB hybrid search | Opportunity Agent (gap analysis, concept expansion, ranking) |
| Grounding source | Knowledge base + memory **only** | Interest profile + KB as **seed** |
| Grounding strictness | **Strict** — answer only from retrieved sources | **Loose** — creative leaps allowed |
| Citations | Mandatory on every claim | Mandatory **provenance** per idea (research items + interest signals) |
| Failure to avoid | **Hallucination** — never invent facts not in the KB | **Unjustified ideas** — never propose without traceable "why" |
| When grounding is thin | Web Search (quick) or Research hand-off (§3.1) instead of guessing | Same — ideation never invents the seed it's missing |
| Output shape | Prose answer + inline citations | Ranked list of ideas, each with a "why am I recommending this" trace |

> The asymmetry is intentional. Inquiry must be *trustworthy* (the user is asking
> what they actually have); ideation must be *generative* (the user is asking for
> something new). But ideation is **not** unconstrained — "creative" means *novel
> combinations of real signals*, never *fabricated facts*. Every idea answers
> "why am I recommending **this**, to **you**, **now**?".

### 3.1 The third branch: deciding when the KB isn't enough

Neither branch is allowed to silently degrade into a generic chatbot when retrieval
comes back empty. Instead the agent makes an explicit choice between two escalation
paths, scoped by latency and by what gets written where:

| | **Web Search (tool)** | **Research Agent hand-off** |
|---|---|---|
| When | A quick factual gap — one or two queries' worth | The topic itself is thin in the KB — needs papers/repos/citation context, not just a quick lookup |
| Mechanism | Brainstorming Agent calls the Web Search tool directly, inline in the turn | Brainstorming Agent submits a `ResearchTopic` command — the *same* path `/research` uses (see [impl/06 §1](impl/06-research-agent.md#1-trigger--position-in-the-flow)) |
| Writes to KB / Graph? | **No** — search results are used for this turn's answer only, not persisted | **Yes** — the Research Agent chunks, embeds, and updates the citation/knowledge graph, same as any other trigger |
| Latency | Seconds | Up to minutes (surfaced as a progress message in Slack/CLI, see [impl/02 §3](impl/02-slack-gateway.md#3-brainstorm-in-a-thread-one-thread--one-session)) |
| On completion | Answer the current turn, nothing further | Re-enter the INQUIRY or IDEATION branch with the new findings once the Research Agent returns |

This is the decision that earns Brainstorming its agent status (§2) — it is made
fresh per turn based on how thin the gap is, not on a fixed rule.

---

## 4. New skills & tools required vs reused

Brainstorming is deliberately cheap to build because it leans on the shared skill
registry and existing tools. Mapped against the litmus test, most of the
*computation* is reused; the new agent's own footprint is the routing decision plus
one new skill and one new tool.

| Capability | New or reused | Notes |
|-----------|---------------|-------|
| **Intent routing** | **Reuse** — the Classification skill | Classify each turn as INQUIRY vs IDEATION vs RESEARCH HAND-OFF (same family as activity classification). |
| **Query reformulation / agentic multi-hop** | 🆕 **New skill** | The one genuinely new piece: rewrite a conversational, context-dependent turn ("expand on #2") into one or more standalone retrieval queries, and fan out multi-hop when a single hop is insufficient. |
| **Cited answer synthesis** | **Reuse (constrained)** — Summarization with provenance | A constrained variant of Summarization that **must** attach a source to every claim and emit *"not in your research"* when retrieval is empty. |
| **Idea synthesis + ranking** | **Reuse** — Opportunity Agent skills | Gap analysis, concept expansion, and ranking already live in the Opportunity Agent; ideation calls them with the Interest profile + KB as seed. |
| **Session/turn loop** | Lives in the Brainstorming Agent itself (see §5) | Chat-history management — not a transform, hence not a skill; it's the agent's own orchestration. |

**Tools: one new — Web Search.** Inquiry and ideation still reuse the **vector
store query** (hybrid search over Qdrant) and the **memory store**. But §3.1
introduced a genuine new external side effect: a quick web lookup for a gap too
small to justify a full Research Agent run. That's a new tool, not a skill, because
it's an external action (D4: `Tool = With What`), not a pure transform.

| Tool | New or reused | Notes |
|------|---------------|-------|
| **Web Search** | 🆕 **New tool** | Used only by the Brainstorming Agent's §3.1 escalation; results are scoped to the current turn and never written to the KB (that distinction is what separates it from a Research Agent hand-off). |
| Research Agent invocation (`ResearchTopic` command) | **Reuse** — not a new tool | This isn't a tool call, it's the same Command/Event path `/research` already uses (see [impl/06](impl/06-research-agent.md)) — Brainstorming submits a command to the engine, it doesn't call an external API directly. |

> Why only *one* new skill and *one* new tool: retrieval, summarization-with-
> citations, classification, and idea synthesis all exist for the scheduled loops.
> What they never had to do is **turn a multi-turn human conversation into clean
> retrieval queries** (query reformulation) or **reach outside the KB for a quick
> answer** (Web Search) — those are the two genuine additions.

---

## 5. Session model

A Brainstorm session is **short-term conversational state**, kept deliberately
separate from long-term memory:

| State | Lives in | Lifetime | Example |
|-------|----------|----------|---------|
| **Chat history** (the turns) | Session state (in-memory / per-thread) | The session | "you asked about embeddings, I cited 3 sources" |
| **Long-term memory** | Memory store (SQLite + Qdrant) | Persistent | The KB, interest profile, saved opportunities |

The session holds enough recent chat history to resolve **follow-up turns** that
only make sense in context. These are handed to the **query-reformulation skill**,
which rewrites them into standalone, retrievable form:

| Follow-up turn | Reformulation resolves it to |
|----------------|------------------------------|
| "expand on #2" | the second idea/source from the previous turn, re-queried for more depth |
| "more technical" | the same topic, re-synthesized at a deeper technical altitude |
| "combine with my Rust work" | the current idea **+** the user's "Rust" interest signals and KB items |

> **Separation rule:** the session is ephemeral and never silently writes to
> long-term memory. The *only* bridge from a session into persistent state is the
> explicit `save idea` action (§6). This keeps exploratory chatter out of the
> interest model and the KB — brainstorming out loud shouldn't reshape what the
> engine thinks you care about unless you say so.

---

## 6. Save-back — closing the loop

A brainstorm output is worthless if it evaporates when the session closes. A
`save idea` action **promotes a brainstorm output into a tracked Opportunity** in the
memory store:

```
[ ideation turn produces idea #2 ]
            │  user: "save idea 2"
            ▼
[ Opportunity record written to Memory store ]
   { type: "opportunity",
     title, body,
     provenance: { research_items: [...], interest_signals: [...] },
     source: "brainstorm", status: "accepted",
     created: 2026-06-21 }
            │
            ▼
[ Meta Agent feedback / performance tracking ]
   accepted-idea signal → informs self-improvement & future ranking
```

The saved record is **type-tagged** (`opportunity`) and carries the same provenance
the ideation branch was required to produce. Crucially, saving feeds the **Meta
Agent's feedback / performance tracking** as an **accepted-idea signal**: the engine
learns which recommendations the user actually values, which in turn sharpens future
ideation and the interest model. This is how interactive brainstorming reconnects to
the otherwise-background cognitive loop.

---

## 7. Delivery surface

Brainstorm rides the engine's existing **symmetric interface adapters** — no new
interface logic, just a session-aware surface on each:

| Surface | Shape | Session mapping |
|---------|-------|-----------------|
| **CLI** | `pa brainstorm` opens a REPL | One REPL invocation = one session; `Ctrl-D` / `exit` closes it |
| **Slack** | A bot thread | **One thread = one session**; replies in the thread are follow-up turns |

Both build the same session `Command`s and render the same `Event` stream, so all
three branches, citations, and `save idea` behave identically across surfaces.
Adding Brainstorm to a future interface is just wiring its input/output to that
same session contract.

---

## 8. First slice / phasing

Brainstorm is built **retrieval-first**, because ideation is only trustworthy once
inquiry is.

### Phase 1 — Inquiry, CLI, strict grounding
- `pa brainstorm` REPL with per-turn intent classification (inquiry path only).
- Memory Retrieval + KB hybrid query → **cited** answer synthesis.
- The new **query-reformulation skill** for follow-ups.
- Hard requirement: emit *"that isn't in your research"* on empty retrieval — never
  fabricate.

### Phase 2 — Ideation
- IDEATION branch routes to the Opportunity Agent, seeded by Interest profile + KB.
- Loose grounding with **mandatory per-idea provenance** (research items + interest
  signals).
- Ranked-idea output and idea-targeted follow-ups ("expand on #2").

### Phase 3 — Save-back + Slack
- `save idea` → tracked Opportunity in the memory store; accepted-idea signal to the
  Meta Agent feedback loop (§6).
- Slack surface: one thread = one session, full parity with the CLI REPL.

### Phase 4 — Escalation (Web Search + Research hand-off)
- Web Search tool wired for the quick-gap case (§3.1).
- `ResearchTopic` hand-off to the Research Agent for the thin-topic case, with a
  progress message while it runs (depends on [impl/06](impl/06-research-agent.md)
  existing first — this phase cannot land before the Research Agent does).
- Re-entry: once findings return, resume the INQUIRY/IDEATION branch that triggered
  the hand-off rather than dropping the user back at a blank turn.

> **Why inquiry before ideation, and escalation last.** Ideation grounded in
> *untrustworthy* retrieval is just a generic chatbot wearing the engine's name — it
> would "recommend" things with confident but unverifiable provenance, the exact
> failure mode §3 forbids. Getting strict, cited inquiry right first means ideation
> can *stand on* a retrieval layer the user already trusts. Escalation is built last
> because it's the riskiest branch to get wrong (latency, what gets written where)
> and the first three phases are exactly what it falls back from.

---

## 9. Open questions

1. **Cold start.** When the KB or interest profile is thin (early days, or a brand-new
   topic), how does Brainstorm degrade gracefully? Inquiry can honestly say *"not in
   your research"* — but ideation needs *some* seed. Should it fall back to
   interest-only ideation, refuse, or explicitly flag low-confidence?
2. ~~**Session-triggered ingestion.**~~ **Resolved.** A session *can* trigger
   research mid-conversation, with clear boundaries: it's not the foreground
   reaching into the old scheduled pipeline (that pipeline is activity-only now,
   see [impl/04](impl/04-daily-research-agent.md)) — it's the Brainstorming Agent
   submitting the exact same `ResearchTopic` command a manual `/research` would,
   to the same Research Agent. The boundary that resolves the original "blurs
   interactive vs. background" worry: latency is surfaced explicitly (a progress
   message, never a silent stall — [impl/02 §3](impl/02-slack-gateway.md#3-brainstorm-in-a-thread-one-thread--one-session)),
   and what it writes to the KB/graph is identical to any other Research Agent
   run — no special-cased "session write." Full design: §3.1 above and
   [impl/06-research-agent.md](impl/06-research-agent.md).
3. **Where saved ideas live.** A dedicated **opportunities store**, or the existing
   **memory store with a `type: opportunity` tag**? The tag approach (assumed in §6)
   is cheaper and keeps provenance co-located; a separate store may be warranted if
   opportunities grow their own lifecycle (status transitions, scheduling, decay).

---

## 10. Success metrics

Brainstorm succeeds when it can answer the user's core vision questions — on demand,
trustably, and traceably:

| Vision question | How Brainstorm answers it | Branch |
|-----------------|---------------------------|--------|
| *"What does my research say about X?"* | Cited inquiry answer, or honest *"not in your research"* | Inquiry |
| *"What should I build next?"* | Ranked ideas seeded by interest + KB | Ideation |
| *"Why are you recommending this?"* | Per-idea provenance: the exact research items **and** interest signals behind it | Ideation |
| *"How does this connect to my previous work?"* | Multi-hop reformulation linking current topic to past KB items / interests ("combine with my Rust work") | Both |
| *"I don't think you know enough about this — go find out"* | `ResearchTopic` hand-off, then resumed inquiry/ideation with the new findings | Research hand-off |

Supporting signals: **zero-hallucination rate** on inquiry (no claim without a
citation), **provenance coverage** on ideation (every idea traces back), the
**accepted-idea rate** (`save idea` invocations) flowing into the feedback loop (§6),
and the **escalation precision** (how often a Web Search or Research hand-off was
actually warranted vs. KB coverage that was there all along — a high false-escalation
rate means the routing decision in §3.1 needs tuning).

---

## Related Documents

- [personal-assistant.plans.md](personal-assistant.plans.md) — the master architecture doc; D4 (agent/skill/tool litmus test) and D6 (Meta's human-reviewed self-modification authority)
- [agent.architecture-guide.md](agent.architecture-guide.md) — the five-agent table and the "one job per agent" discipline
- [impl/05-meta-agent-and-skills.md](impl/05-meta-agent-and-skills.md) — Meta Agent (feedback loop), Interest Agent, Opportunity Agent, the shared skill registry
- [impl/06-research-agent.md](impl/06-research-agent.md) — the Research Agent invoked by the §3.1 hand-off
- [impl/03-vector-db-and-storage.md](impl/03-vector-db-and-storage.md) — hybrid retrieval + graph store over the memory store used by all three branches
- [impl/01-cli-and-core-engine.md](impl/01-cli-and-core-engine.md) / [impl/02-slack-gateway.md](impl/02-slack-gateway.md) — the `Brainstorm`/`ResearchTopic` command contracts and their CLI/Slack bindings
