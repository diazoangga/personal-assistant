# Brainstorming Agent

The conversational agent. Answers cited questions (`Ask`) and runs ideation sessions
(`Brainstorm`) over the knowledge base, with web search. It is the only agent built on
**LangGraph**, and the only one that needs LLM **tool-calling**.

## Two LLMs, on purpose

The engine's shared `OpenRouterRuntime` has no native tool-calling
([ADR-0003](../architecture/decisions/0003-openrouter-no-native-tools.md)). So the agent
holds two handles:

| Handle | Type | Used by |
|---|---|---|
| `reasoning_llm` | `OpenRouterRuntime` (shared) | plain-text judgment nodes: safety, critique, interest extraction |
| `chat_llm` | `langchain_openai.ChatOpenAI` (OpenRouter base URL) | the `assistant` node, which must emit `tool_calls` |

`chat_llm` is injectable (`chat_llm=` constructor arg) as a test seam so unit tests can
supply a fake tool-calling model instead of hitting OpenRouter.

## The graph

Built **fresh per turn** by `build_graph` — nodes are closures over this turn's `ToolDeps`
/ `TurnContext`, so user/thread scoping stays correct without threading non-serializable
deps through checkpointed state. Compiling a handful of nodes per turn is cheap.

```
START → intake → safety ─(blocked?)─▶ END
                   │ ok
                   ▼
              assistant ──(tool_calls?)──▶ tools ──┐
                   │ no tool_calls                  │
                   ▼                                │
                critique ◀───────────────────────── ┘ (loop back to assistant)
                   │ needs_more & iteration<max → assistant
                   │ else
                   ▼
            register_interest → END
```

| Node | Module | Role |
|---|---|---|
| `intake` | `nodes/intake.py` | normalise the incoming turn |
| `safety` | `nodes/safety.py` | gate unsafe queries (`reasoning_llm`); sets `query_blocked` |
| `assistant` | `nodes/assistant.py` | the tool-calling brain (`chat_llm` + system prompt + `ToolDeps`) |
| `tools` | `nodes/tools_executor.py` | execute requested tools, append results, loop back |
| `critique` | `nodes/critique.py` | judge completeness (`reasoning_llm`); sets `needs_more` |
| `register_interest` | `nodes/register_interest.py` | extract interests from the exchange and feed them back into the model |

The `assistant ⇄ tools` loop and the `critique → assistant` re-entry are both bounded by
`max_iterations` (default 5).

## Tools

`tools.py` defines the tool surface and `ToolDeps` (store, `reasoning_llm`, `user_id`,
`thread_id`, `TurnContext`, `tavily_api_key`). Tools: **web search** (Tavily, when
`tavily_api_key` is set), **knowledge-base search** over the unified store, and **citation
retrieval**. Sources gathered during a turn are collected on `TurnContext.gathered_sources`
and surfaced as `citations` on the answer.

## Public API

```python
agent.answer(query, user_id="cli", thread_id?) -> BrainstormAnswer(text, citations)
agent.run_session(job_id, cmd, publish)        # streams Message + Result via the bus
```

`core/engine.py` routes `Ask → answer()` and `Brainstorm → run_session()`. High-quality
answers from the engine's `ask` path are auto-saved as `knowledge_entries` (quality ≥
`quality_threshold`, default 0.65) — see [storage/knowledge-store.md](../storage/knowledge-store.md).

## Gotchas

- **Stateful sessions** — concurrent sessions need distinct `thread_id`s. Cross-restart
  session persistence is not implemented (the graph is rebuilt per turn; durable history
  lives in `conversation_*` tables, not in graph checkpoints).
- **Tool-calling quality** is bounded by the chosen OpenRouter model.

---

> **Source of truth:** `src/agents/brainstorming/{agent,graph,state,tools}.py`,
> `src/agents/brainstorming/nodes/`, `prompts/system_prompt.txt`.
