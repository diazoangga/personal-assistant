# ADR-0003: OpenRouter runtime, and where tool-calling lives

**Status:** Accepted · **Date:** 2026-06 (retroactive)

## Context

We standardised on OpenRouter's free tier (`google/gemma-4-26b-a4b-it:free`) to keep the
project zero-cost. Our LLM access is a thin custom `httpx` client (`llm/openrouter.py`)
that exposes `chat`/`complete`/`embed`. Crucially, **this runtime has no native
tool/function-calling** — it posts a prompt and returns text. But the Brainstorming Agent
is a tool-using agent (web search, KB search, citation lookup) built on LangGraph, which
expects a model that can emit structured `tool_calls`.

## Decision

Keep the lightweight `OpenRouterRuntime` as the shared engine LLM for all plain-text
judgment calls (classification, synthesis, summarisation, safety/critique). For the **one**
path that needs tool-calling — the Brainstorming Agent's `assistant` node — use
`langchain_openai.ChatOpenAI` pointed at the same OpenRouter base URL, which provides the
tool-calling protocol LangGraph needs. The agent therefore holds two LLM handles:
`reasoning_llm` (OpenRouterRuntime) and `chat_llm` (ChatOpenAI).

## Consequences

- **+** Cheap, dependency-light LLM access everywhere it suffices.
- **+** Tool-calling works in the one place it's required, without rewriting the runtime.
- **−** Two LLM client types coexist; contributors must know which to use where.
- **−** Tool-calling quality depends on the chosen OpenRouter model actually supporting
  function-calling well; the free Gemma model is the weak link.
- This split is the single biggest fork in the Brainstorming Agent design — see
  [agents/brainstorming.md](../../agents/brainstorming.md).
