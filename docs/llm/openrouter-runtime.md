# OpenRouter Runtime

`OpenRouterRuntime` (`llm/openrouter.py`) is the shared LLM client for the whole engine: a
thin async `httpx` wrapper over the OpenRouter API with model routing, rate limiting,
retries, and embeddings. It deliberately does **not** implement tool-calling — see
[ADR-0003](../architecture/decisions/0003-openrouter-no-native-tools.md).

## Interface

```python
runtime.chat(messages, model_role="meta", **kw) -> Response(.content)   # OpenAI-shaped messages
runtime.complete(role, prompt, **kw) -> str                            # single prompt
runtime.embed(texts) -> list[list[float]]                              # embeddings
runtime.get_usage_stats() -> dict
```

`chat` flattens messages to a prompt and calls `complete`. `**kw` passes
`max_tokens` (default 2048) and `temperature` (default 0.7).

## Model routing

Models are chosen per **role**, from the `[llm]` config:

| Role | Default model |
|---|---|
| `meta` | `google/gemma-4-26b-a4b-it:free` |
| `reasoning` | `google/gemma-4-26b-a4b-it:free` |
| embeddings | `qwen/qwen3-embedding-8b` |

Agents pass `role`/`model_role` to pick the model. The free Gemma tier is the zero-cost
default; swap models in config without code changes.

## Rate limiting & retries

- An `asyncio.Semaphore` caps concurrency (`rate_limit_per_minute // 60`).
- `_check_rate_limits` enforces a rolling per-minute window (~60 req/min) and an approximate
  daily cap (~1000 req/day), sleeping or raising `RateLimitError` as needed.
- `complete` retries up to `max_retries` (default 3) with exponential backoff; HTTP 429
  backs off and retries, other failures raise `APIError`.

## Where each path is used

| Caller | Method | Role |
|---|---|---|
| Interest classification | `complete` | `reasoning` |
| Research synthesis/extraction/summary | `complete` | `reasoning` |
| Engine `ask` + answer-quality scoring | `chat` | `meta` |
| Interest signal/text embedding | `embed` | — |
| Brainstorming safety/critique/interest nodes | via `reasoning_llm` | `reasoning` |
| Brainstorming `assistant` (tool-calling) | **not this runtime** — `langchain_openai.ChatOpenAI` | — |

## Config (`[llm]` / env)

`base_url` (`https://openrouter.ai/api/v1`), `meta_model`, `reasoning_model`,
`embedding_model`, `rate_limit_per_minute` (60), `rate_limit_per_day` (1000),
`max_retries` (3). API key from `OPENROUTER_API_KEY`.

---

> **Source of truth:** `src/llm/openrouter.py`, `config/settings.toml` (`[llm]`).
