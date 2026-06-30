# Brainstorming Agent — Profile & Implementation Plan

> Status: **Design / Plan** (no code yet). This document defines *what* the
> Brainstorming Agent is, *what it can do*, *how it decides*, and *how we'll build it*.
> Reference architecture studied: `D:/Mandiri/sdlc-studio-core/src/agent/brainstorming`
> (LangGraph agentic loop: `assistant → tools? → assistant → END`).

**Author target:** Personal Assistant (5-agent cognitive engine)
**Created:** 2026-06-22

---

## 1. Why a Brainstorming Agent

The other agents are *signal-driven* and *autonomous* — they watch your activity and act in
the background. The Brainstorming Agent is the **interactive, conversational front door**:
the agent you actually *talk to*. It exists to turn a vague thought ("I want to build X",
"what's the state of the art in Y?", "is this idea novel?") into:

- grounded answers (knowledge base + live web),
- new entries in the knowledge graph (research),
- registered **interests** (so the rest of the system learns from the conversation),
- and concrete **solution proposals** / gap analyses.

Crucially, it is **self-supervising**: it judges whether its own answer is good enough yet,
and iterates (calls more tools, researches deeper) until it is — rather than returning a
shallow first draft.

### Position in the system

```
                      ┌────────────────────────────────────────────┐
   user (CLI/REPL) ──▶│            BRAINSTORMING AGENT              │
                      │   LangGraph agentic loop + self-critique    │
                      └───────┬───────────────┬───────────────┬─────┘
                              │ delegates      │ tools          │ writes
                  ┌───────────▼──┐   ┌─────────▼────────┐  ┌────▼─────────────────┐
                  │ Research      │   │ web_search       │  │ UnifiedKnowledgeStore │
                  │ Agent         │   │ (new tool)       │  │  interests/concepts/  │
                  │ (deep_research│   │ search_kb        │  │  citations/graph      │
                  │  /knowledge)  │   │ show_graph ...   │  └───────────────────────┘
                  └───────────────┘   └──────────────────┘
                              │
                  ┌───────────▼──┐
                  │ Interest      │  ← register_interest (also fed by web/github signals)
                  │ Agent / store │
                  └───────────────┘
```

---

## 2. Agent Profile

| Attribute | Value |
|---|---|
| **Name** | Brainstorming Agent |
| **Type** | Interactive, conversational, multi-turn |
| **Engine** | LangGraph `StateGraph` (agentic tool loop) |
| **Invocation** | `pa brainstorm "<topic>"`, `pa chat` / REPL, future Slack |
| **Autonomy** | Self-supervising: decides when to use tools and when the answer is "done" |
| **Persona** | A sharp, curious research partner. Proposes, critiques, and grounds claims in evidence. Asks clarifying questions when the request is ambiguous. Never fabricates citations. |
| **Memory** | Per-thread conversation state (checkpointed) + writes durable interests/knowledge to the shared store |
| **Outputs** | Grounded chat answers, research-graph updates, registered interests, solution proposals, gap analyses |

### Behavioral contract

1. **Ground before answering.** Prefer `search_knowledge_base` first; fall back to
   `web_search` / `deep_research` when the KB is thin.
2. **Self-critique loop.** After drafting, judge: *is this complete, grounded, and
   actionable?* If not, call more tools and revise (bounded by `max_iterations`).
3. **Always learn.** If the conversation reveals user interest in a topic, call
   `register_interest` — this is the link that lets *talking* to the agent train the
   interest model (alongside GitHub/web signals).
4. **Persist value.** When research yields durable facts, call `register_knowledge` so
   future questions are answered from the graph, not re-researched.
5. **Be honest about uncertainty.** Distinguish KB-grounded facts from web claims from
   model priors.

---

## 3. Capabilities

The nine requested capabilities, each mapped to its backing (tool / skill / agent
delegation) and current readiness. "Tool" = bound to the LLM and callable in the agentic
loop. "Delegates" = calls another agent's method.

| # | Capability | Kind | Backing | Readiness |
|---|---|---|---|---|
| 1 | `web_search` | Tool | **New** web-search tool (provider: Tavily/SerpAPI/Brave/DuckDuckGo) via `httpx` | ❌ build new |
| 2 | `search_knowledge_base` | Tool | `UnifiedKnowledgeStore` + Qdrant (`vector.py`) semantic search over `knowledge_entries`/`concepts` | 🟡 store exists; thin search wrapper needed |
| 3 | `register_interest` | Tool → delegates | `InterestAgent` / `UnifiedKnowledgeStore.upsert_interest` (strength policy below) | ✅ store ready |
| 4 | `show_research_graph` | Tool | `UnifiedKnowledgeStore.relevant_subgraphs(interests=…)` → nodes/edges | 🟡 method exists; needs render/format |
| 5 | `register_knowledge` (research) | Tool → delegates | `Research Agent` populate path → `upsert_citation`/`upsert_concept`/`add_concept_relationship` | 🟠 Research Agent currently unwired (see §8) |
| 6 | `deep_research` | Tool → delegates | `Research Agent.research(topic, depth)` (arXiv fetch → entity/relationship extraction) | 🟠 Research Agent currently unwired |
| 7 | `research_documentation` | Skill | LLM skill: synthesize a structured doc (overview → key concepts → references) from KB + web + graph | ❌ build new skill |
| 8 | `research_gap_analysis` | Skill | LLM skill: compare what's known (graph/KB) vs. the question → list gaps & open problems | ❌ build new skill |
| 9 | `solution_proposal` | Skill | LLM skill: synthesize a concrete proposal (approach, components, risks, next steps) grounded in 2,4,6 | ❌ build new skill |

### Capability detail

- **`web_search(query, max_results)`** → list of `{title, url, snippet}`. Results can be
  fed into `register_knowledge` and can trigger `register_interest` (a topic the user is
  exploring via the web is an interest signal).
- **`search_knowledge_base(query, k)`** → top-`k` `knowledge_entries`/`concepts` with
  scores. The first stop for grounding.
- **`register_interest(topic, source, strength?)`** → upserts an interest. `source` ∈
  {`conversation`, `web_search`, `github`, `explicit`}. Strength defaults by source (§5).
- **`show_research_graph(topic?, depth)`** → `(nodes, edges)` subgraph around a topic via
  BFS; formatted for display.
- **`register_knowledge(topic|payload)`** → runs/streams the Research Agent populate path,
  writing citations/concepts/relationships.
- **`deep_research(topic, depth)`** → full Research Agent run; returns a summary + counts.
- **`research_documentation(topic)`** → a structured markdown brief grounded in KB+web+graph.
- **`research_gap_analysis(topic)`** → enumerates what the graph/KB already covers vs. what's
  missing/uncertain → a prioritized gap list.
- **`solution_proposal(problem)`** → a concrete proposal: approach, components, trade-offs,
  risks, and next actions, citing the evidence gathered.

---

## 4. Architecture — Self-Supervising Agentic Loop

Modeled on the reference repo's simplified agentic graph (LLM picks tools dynamically;
tools loop back; no tool calls → end), plus an explicit **critique gate** so the agent
judges its own output.

```
START
  │
  ▼
intake ───────────────▶ (normalize query, attach thread context)
  │
  ▼
safety ───────────────▶ block disallowed queries → END(blocked)
  │ ok
  ▼
assistant ◀───────────────────────────┐   (LLM: think + select tools OR draft answer)
  │                                    │
  ├─ has tool_calls? ──▶ tools ────────┘   (execute web_search / search_kb / deep_research /
  │                                          register_* / show_graph; inject user_id/context)
  │
  └─ no tool_calls ──▶ critique         (LLM-as-judge: complete? grounded? actionable?)
                          │
              ┌───────────┴───────────┐
        needs_more?                   good_enough?
          │ (iteration<max)            │
          └────▶ assistant            ▼
                                   register_interest         (auto: extract interests from
                                       │                      the whole conversation)
                                       ▼
                                     END
```

**How it "supervises and judges itself":**

- The **assistant node** binds all tools and decides each turn whether to gather more
  evidence (emit `tool_calls`) or draft a final answer (no `tool_calls`).
- The **critique node** is an LLM-as-judge that scores the draft on *completeness,
  grounding, actionability*. If it fails the bar and `iteration < max_iterations`, the loop
  returns to `assistant` with the critique appended as guidance; otherwise it finalizes.
- `max_iterations` (default 5) bounds cost; a circuit breaker stops runaway loops.

This is the personal-assistant analogue of the reference's `assistant ↔ tools` loop, with
the critique gate making the "is my response appropriate yet?" decision explicit.

### Graph nodes

| Node | Responsibility |
|---|---|
| `intake` | Load/normalize query, hydrate thread state, list available tools |
| `safety` | Guardrail: block unsafe/disallowed queries (port lightweight version of reference `safety.py`) |
| `assistant` | LLM reasoning + dynamic tool selection (binds the 9 capabilities) |
| `tools` | Execute selected tools with context injection (`user_id`, `thread_id`) |
| `critique` | LLM-as-judge; sets `needs_more`/`should_end` and feeds guidance back |
| `register_interest` | Extract & persist interests from the conversation before ending |

---

## 5. Interest Registration (cross-cutting requirement)

> "The interest can be found if the user talks with the brainstorming agent (via CLI query
> and conversation), or via web_search, GitHub, etc."

The Brainstorming Agent is a **first-class interest signal source**. Two paths:

1. **Explicit tool call** — the assistant calls `register_interest(topic, source)` mid-loop
   when the user clearly cares about a topic ("I'm really into X").
2. **Automatic end-of-turn extraction** — the `register_interest` node runs an LLM pass over
   the conversation (and any web/research results gathered) to extract topics, then upserts
   them. This mirrors `main_engine.ask()`'s batch extraction, but per-conversation.

**Strength policy (consistent with existing engine conventions):**

| Source | Strength | Rationale |
|---|---|---|
| `explicit` (user says "research X" / "I'm interested in X") | 0.85 | direct intent |
| `conversation` (inferred from chat) | 0.55 | inferred intent |
| `web_search` (topic the user actively explored) | 0.50 | behavioral signal |
| `github` (existing connector) | per Interest Agent | unchanged |

All of these feed the same decaying interest model (`get_strength`, half-life 720h) and can
trigger downstream auto-research once strength accumulates — closing the loop between
*conversation* and the *autonomous* agents.

---

## 6. State Schema (LangGraph `BrainstormingState`)

A slimmed adaptation of the reference's TypedDict (we drop Jira/PRD/file-upload fields not
relevant here):

```python
class BrainstormingState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]   # conversation
    user_id: str
    thread_id: str

    user_input: Optional[str]

    # control
    iteration: int
    max_iterations: int            # default 5
    should_end: bool
    query_blocked: bool
    needs_more: bool               # set by critique

    # working memory
    tool_results: list[dict]       # raw outputs from this turn's tools
    verified_facts: Annotated[list[str], append]   # grounding that must survive
    gathered_sources: list[dict]   # {title,url,snippet} from web/kb for citations

    # structured outputs
    research_summary: Optional[str]
    gap_analysis: Optional[dict]
    proposal: Optional[dict]
    registered_interests: list[str]

    # critique
    critique_score: Optional[float]
    critique_notes: Optional[str]

    error: Optional[str]
```

State is checkpointed per `thread_id` (LangGraph `AsyncSqliteSaver`, reusing the SQLite
infra) so conversations are resumable.

---

## 7. Key Decision — Tool Calling Mechanism ⚠️

The current `OpenRouterRuntime` (`src/llm/openrouter.py`) **flattens all messages into one
prompt and returns only text** — it does **not** pass `tools`/`tool_choice` nor parse
`tool_calls`. An agentic tool loop needs one of:

| Option | Approach | Pros | Cons |
|---|---|---|---|
| **A. Native tool-calling via LangChain** *(recommended)* | Use `ChatOpenAI(base_url=OpenRouter)` with `.bind_tools()` for this agent | Matches reference exactly; clean `tool_calls`; LangGraph-native | Adds `langchain-openai` dep; model must support function-calling |
| **B. Extend `OpenRouterRuntime`** | Add `tools`/`tool_choice` passthrough + `tool_calls` parsing to the existing runtime | No new heavy dep; reused everywhere | More custom code; must hand-roll the tool-call message protocol |
| **C. Prompt-based JSON dispatch (ReAct)** | LLM emits `{"tool": ..., "args": {...}}`; we parse & dispatch | Works with *any* model incl. Gemma free | Brittle parsing; no parallel tool calls; diverges from reference |

**Recommendation:** **Option A** for the Brainstorming Agent specifically (it's the most
faithful to the studied reference and the natural LangGraph fit), keeping the existing
`OpenRouterRuntime` for the other agents. If the configured free model proves unreliable at
function-calling, fall back to **Option C** behind the same tool interface.

> This is the one decision worth confirming before coding, because it determines the
> assistant/tools node implementation. The capability surface (the 9 tools) is identical
> regardless of which option we pick.

---

## 8. Integration with the Existing System

- **Engine wiring** — construct `BrainstormingAgent` in
  `PersonalAssistantEngine.initialize()` and `engine.register_agent("brainstorm", agent)`.
  This finally makes `Engine._handle_ask` / `_handle_brainstorm` reachable via the command
  path (today they reference an unregistered `"brainstorm"` agent).
- **CLI** — `pa brainstorm "<topic>"` already calls `engine.brainstorm()`; reroute that to
  the agent. Add a `pa chat` / REPL `chat` mode for multi-turn sessions.
- **Dependencies on other agents:**
  - `deep_research` / `register_knowledge` delegate to the **Research Agent**. ⚠️ The
    Research Agent + Supervisor packages are **currently unwired** (only `skills/`/`tools/`
    remain on disk; `agent.py` files and `main_engine` wiring were rolled back). Plan
    assumes we **re-establish the Research Agent** (or stub these two capabilities behind a
    feature flag until it returns).
  - `register_interest` uses the **Interest Agent** / store, which **is** wired today.
- **Storage** — all durable writes go to `UnifiedKnowledgeStore` (`knowledge.db`); semantic
  search uses Qdrant via `vector.py`.

---

## 9. Implementation Plan (phased)

### Phase B0 — Foundations
1. Decide tool-calling mechanism (§7) — confirm Option A vs C.
2. Create package skeleton:
   ```
   src/agents/brainstorming/
     __init__.py
     agent.py              # BrainstormingAgent: build graph, run_session/answer
     state.py              # BrainstormingState
     graph.py              # LangGraph construction (nodes + edges)
     nodes/
       intake.py  safety.py  assistant.py  tools_executor.py  critique.py  register_interest.py
     tools/
       __init__.py         # get_available_tools() registry + bind helpers
       web_search.py
       knowledge_base.py   # search_knowledge_base, register_knowledge, show_research_graph
       interest.py         # register_interest
       research.py         # deep_research (delegates to Research Agent)
     skills/
       research_documentation.py  research_gap_analysis.py  solution_proposal.py
     prompts/              # system_prompt.txt, critique.txt, interest_extraction.txt
   ```

### Phase B1 — Read-only capabilities (no external side effects)
3. `search_knowledge_base` (KB + Qdrant wrapper).
4. `web_search` (provider behind an interface; config-driven API key).
5. `show_research_graph` (format `relevant_subgraphs` output).
6. Minimal graph: `intake → safety → assistant → tools? → assistant → END` (no critique
   yet). Verify the tool loop end-to-end with these three tools.

### Phase B2 — Self-supervision
7. Add `critique` node (LLM-as-judge) + `needs_more`/`max_iterations`/circuit breaker.
8. Add `register_interest` node (auto end-of-turn extraction) + the explicit tool, with the
   §5 strength policy.

### Phase B3 — Write/synthesis capabilities
9. `deep_research` + `register_knowledge` (delegate to Research Agent; gate behind a flag if
   the Research Agent is still unwired).
10. Skills: `research_documentation`, `research_gap_analysis`, `solution_proposal`.

### Phase B4 — Integration & polish
11. Wire into `PersonalAssistantEngine` + `register_agent("brainstorm", …)`; reroute
    `pa brainstorm`; add `pa chat` REPL.
12. Checkpointing (`AsyncSqliteSaver`), streaming `Progress`/`Message` events to the CLI.
13. Tests (see §11) + docs update.

---

## 10. Data-Flow Examples

**"What's the state of the art in retrieval-augmented generation, and is my idea novel?"**

```
intake → safety → assistant
  └ tool: search_knowledge_base("RAG")            → thin results
  └ tool: web_search("RAG state of the art 2026")  → 8 sources
  └ tool: deep_research("retrieval augmented generation", depth=normal)
                                                    → papers/concepts into graph
assistant → (drafts answer) → critique
  └ score 0.6 < bar, notes "novelty not assessed"  → needs_more
assistant
  └ skill: research_gap_analysis("RAG")            → gaps vs. user's idea
  └ skill: solution_proposal(user idea)            → proposal grounded in sources
assistant → (final answer) → critique 0.85 ok
register_interest: ["retrieval augmented generation"@0.55] → END
```

---

## 11. Testing Strategy

- **Unit (mocked LLM/tools):** each tool returns expected shape; `register_interest`
  upserts with correct strength per source; `critique` flips `needs_more` correctly.
- **Graph (FakeLLM):** loop terminates (no infinite iteration); `max_iterations` respected;
  `should_end` honored; safety block path ends cleanly.
- **Integration:** `BrainstormingAgent` registered on the engine; `pa brainstorm` routes to
  it; an interest appears in the store after a session.
- **Network-gated (skipped by default):** real `web_search`, real `deep_research`.
- Follow repo conventions: `poetry run pytest`, async via `pytest-asyncio`, temp SQLite DBs.

---

## 12. Open Decisions & Risks

1. **Tool-calling mechanism (§7)** — needs confirmation (Option A recommended).
2. **Web-search provider** — Tavily (LLM-friendly, paid free-tier), Brave, SerpAPI, or
   DuckDuckGo (no key). Pick one; put the key in `.env` / `settings.toml`.
3. **Research Agent availability** — capabilities 5 & 6 depend on it; it's currently
   unwired. Decide: re-wire now, or ship B1–B2 first and flag 5/6 as "coming soon".
4. **Free-model reliability** — Gemma free tier may be weak at function-calling and
   long agentic loops; keep `max_iterations` low and Option C as fallback.
5. **Cost/latency** — critique adds an LLM call per finalization; circuit breaker required.

---

*Next step: confirm §7 (tool-calling) and §12.2 (web provider), then implement Phase B0–B1.*
