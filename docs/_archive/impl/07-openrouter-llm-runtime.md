---
title: "Implementation: OpenRouter LLM Runtime"
created: 2026-06-21
updated: 2026-06-21
version: 1.0.0
status: Draft
tags: [implementation, llm, openrouter, gemma, completions]
changelog:
  - version: 1.0.0
    date: 2026-06-21
      changes: "Initial OpenRouter runtime implementation with Gemma4-31B free tier"
related:
  - ../personal-assistant.plans.md
  - ../personal-assistant.implementation.md
  - 05-meta-agent-and-skills.md
reference:
  - https://openrouter.ai/docs
  - https://openrouter.ai/models
---

> Whenever this documentation file changes, update the `updated` field and append a new entry to `changelog` describing the revision.

# Implementation: OpenRouter LLM Runtime

This doc replaces the Ollama runtime assumptions in other docs. The system now uses **OpenRouter API** with **Gemma4-31B (free tier)** for all LLM completions, while keeping embeddings local (Ollama or sentence-transformers).

> **Why Gemma4-31B free tier:** It provides strong reasoning capabilities at zero cost, avoids local VRAM constraints, and OpenRouter's unified API makes model swaps trivial if needed later.

---

## 1. Setup & Configuration

### 1.1 Get Your API Key

1. Sign up at https://openrouter.ai
2. Generate an API key in your dashboard
3. Add to `.env`:

```bash
OPENROUTER_API_KEY=sk-or-v1-...your-key-here
```

### 1.2 Configuration

`config/settings.toml`:

```toml
[models]
meta      = "google/gemma-3b-european-union:free"  # or "google/gemma-2-9b-it:free" if available
reasoning = "google/gemma-3b-european-union:free"  # same model for both roles (free tier)
embedding = "nomic-embed-text"                      # local embedding (Ollama or sentence-transformers)

[runtime]
openrouter_api_key = "${OPENROUTER_API_KEY}"
openrouter_base_url = "https://openrouter.ai/api/v1"
max_concurrent_requests = 3      # stay within free tier rate limits
request_timeout = 60             # seconds; increase for long reasoning runs
retry_with_backoff = true       # retry on rate limit (429) errors
max_retries = 3

[runtime.rate_limits]
# OpenRouter free tier limits (check current limits on openrouter.ai/models)
requests_per_minute = 60
requests_per_day = 1000
tokens_per_minute = 4000        # approximate; adjust based on actual usage
```

---

## 2. The OpenRouter Runtime

```python
# src/llm/openrouter.py
import os
import time
import asyncio
from typing import Optional
import httpx
from dataclasses import dataclass

@dataclass
class CompletionRequest:
    role: str
    prompt: str
    max_tokens: int = 2048
    temperature: float = 0.7

class OpenRouterRuntime:
    def __init__(self, config: dict):
        self.api_key = config["openrouter_api_key"]
        self.base_url = config.get("openrouter_base_url", "https://openrouter.ai/api/v1")
        self.max_concurrent = config.get("max_concurrent_requests", 3)
        self.timeout = config.get("request_timeout", 60)
        self.max_retries = config.get("max_retries", 3)
        
        # Rate limiting
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        self._request_times = []
        self._daily_count = 0
        self._daily_reset = time.time() + 86400
        
        # Model routing
        self.role_models = {
            "meta": config.get("models.meta", "google/gemma-3b-european-union:free"),
            "reasoning": config.get("models.reasoning", "google/gemma-3b-european-union:free"),
        }
        
        # Local embedding runtime (still needed for KB)
        self._embedding_runtime = LocalEmbeddingRuntime(config)
    
    async def complete(self, role: str, prompt: str, **kwargs) -> str:
        """
        Make a completion request to OpenRouter.
        
        Args:
            role: "meta" or "reasoning" — determines which model to use
            prompt: The full prompt text
            **kwargs: max_tokens, temperature, etc.
        
        Returns:
            The completion text
        
        Raises:
            RateLimitError: If free tier limits are exceeded
            APIError: On API failures
        """
        model = self.role_models.get(role, self.role_models["meta"])
        
        async with self._semaphore:
            await self._check_rate_limits()
            
            for attempt in range(self.max_retries):
                try:
                    return await self._make_request(model, prompt, **kwargs)
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429 and attempt < self.max_retries - 1:
                        wait_time = (2 ** attempt) * 2  # exponential backoff
                        await asyncio.sleep(wait_time)
                        continue
                    raise
        
        raise RuntimeError(f"Failed after {self.max_retries} retries")
    
    async def _make_request(self, model: str, prompt: str, **kwargs) -> str:
        """Low-level API call."""
        max_tokens = kwargs.get("max_tokens", 2048)
        temperature = kwargs.get("temperature", 0.7)
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/yourusername/personal-assistant",  # required by OpenRouter
            "X-Title": "Personal Assistant",
        }
        
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            
            data = response.json()
            return data["choices"][0]["message"]["content"]
    
    async def _check_rate_limits(self):
        """Check and enforce rate limits before making a request."""
        now = time.time()
        
        # Reset daily counter if needed
        if now > self._daily_reset:
            self._daily_count = 0
            self._daily_reset = now + 86400
        
        # Check daily limit
        if self._daily_count >= 1000:  # adjust based on actual free tier limit
            raise RateLimitError("Daily request limit exceeded")
        
        # Check per-minute limit
        self._request_times = [t for t in self._request_times if now - t < 60]
        if len(self._request_times) >= 60:  # adjust based on actual free tier limit
            wait_time = 60 - (now - self._request_times[0])
            if wait_time > 0:
                await asyncio.sleep(wait_time)
        
        self._request_times.append(now)
        self._daily_count += 1
    
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings using local embedding runtime.
        
        Embeddings stay local for privacy and cost reasons.
        """
        return await self._embedding_runtime.embed(texts)


class LocalEmbeddingRuntime:
    """Local embedding generation (Ollama or sentence-transformers)."""
    
    def __init__(self, config: dict):
        # Option 1: Ollama embeddings (still useful even if completions are cloud)
        self.ollama_host = config.get("ollama_host", "http://localhost:11434")
        self.embedding_model = config.get("models.embedding", "nomic-embed-text")
        
        # Option 2: sentence-transformers (pure Python, no Ollama needed)
        # from sentence_transformers import SentenceTransformer
        # self.model = SentenceTransformer("nomic-ai/nomic-embed-text-v1.5")
    
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings locally."""
        # Implementation depends on chosen backend (Ollama vs sentence-transformers)
        # For now, stub with Ollama call
        embeddings = []
        async with httpx.AsyncClient() as client:
            for text in texts:
                response = await client.post(
                    f"{self.ollama_host}/api/embeddings",
                    json={"model": self.embedding_model, "prompt": text},
                )
                response.raise_for_status()
                embeddings.append(response.json()["embedding"])
        return embeddings


class RateLimitError(Exception):
    """Raised when OpenRouter free tier rate limits are exceeded."""
    pass


class APIError(Exception):
    """Raised on OpenRouter API failures."""
    pass
```

---

## 3. Usage in Agents & Skills

Agents and skills request completions by **role**, not model name:

```python
# src/agents/meta/graph.py
async def meta_router(skills, tools, llm: OpenRouterRuntime):
    async def node(state: MetaState) -> MetaState:
        prompt = build_classification_prompt(state)
        activity = await llm.complete(role="meta", prompt=prompt, temperature=0.3)
        state["activity"] = parse_activity(activity)
        return state
    return node

# src/skills/topic_extraction.py
async def run(texts: list[str], *, llm: OpenRouterRuntime, **kwargs) -> list[Topic]:
    prompt = build_topic_prompt(texts)
    response = await llm.complete(role="meta", prompt=prompt)
    return parse_topics(response)

# src/agents/opportunity.py
async def concept_synthesis(interests, context, *, llm: OpenRouterRuntime, **kwargs) -> list[Idea]:
    prompt = build_synthesis_prompt(interests, context)
    response = await llm.complete(role="reasoning", prompt=prompt, temperature=0.8)
    return parse_ideas(response)
```

**Key points:**
- Use `role="meta"` for lightweight tasks (classification, routing, simple extractions)
- Use `role="reasoning"` for heavy synthesis (ideation, complex reasoning, brainstorming)
- Both currently map to the same Gemma4-31B free tier model, but the abstraction allows easy swapping later

---

## 4. Embedding Strategy

Embeddings remain **local** for three reasons:

1. **Privacy:** Embeddings encode sensitive content from your activity signals
2. **Cost:** Embedding API calls would burn through free tier credits quickly
3. **Performance:** Local embeddings are fast and don't hit rate limits

### Options:

**Option A: Ollama for embeddings only**
```toml
[runtime]
ollama_host = "http://localhost:11434"  # still need Ollama running

[models]
embedding = "nomic-embed-text"  # pull this model: `ollama pull nomic-embed-text`
```

**Option B: Pure Python (no Ollama)**
```bash
pip install sentence-transformers
```

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("nomic-ai/nomic-embed-text-v1.5")
embeddings = model.encode(texts, convert_to_numpy=True)
```

Recommendation: **Option B** if you want to minimize local dependencies. Ollama is only needed for embeddings now, so sentence-transformers is simpler.

---

## 5. Error Handling & Resilience

```python
# src/llm/openrouter.py (add to OpenRouterRuntime class)

async def complete_with_fallback(self, role: str, prompt: str, **kwargs) -> str:
    """
    Try OpenRouter, fall back to a simpler model or cached response on failure.
    """
    try:
        return await self.complete(role, prompt, **kwargs)
    except RateLimitError:
        # Fall back to a smaller, faster model if available
        fallback_model = "google/gemma-2b-it:free"  # if available
        return await self._make_request(fallback_model, prompt, **kwargs)
    except APIError as e:
        # Log error, return cached/safe response
        logger.error(f"OpenRouter API error: {e}")
        return self._safe_fallback_response(role)
```

---

## 6. Monitoring & Observability

Track API usage to stay within free tier limits:

```python
# src/llm/openrouter.py (add to OpenRouterRuntime class)

def get_usage_stats(self) -> dict:
    """Return current usage statistics."""
    now = time.time()
    requests_last_minute = len([t for t in self._request_times if now - t < 60])
    
    return {
        "requests_this_minute": requests_last_minute,
        "requests_today": self._daily_count,
        "daily_reset_in_hours": (self._daily_reset - now) / 3600,
        "concurrent_requests": self._semaphore._value,
    }
```

Add a CLI command to check usage:

```python
# src/adapters/cli/app.py
@app.command()
def usage():
    """Show OpenRouter API usage stats."""
    engine = build_engine()
    stats = engine.llm.get_usage_stats()
    print_usage_table(stats)
```

---

## 7. Testing

```python
# tests/test_openrouter_runtime.py
import pytest
from unittest.mock import AsyncMock, patch
from src.llm.openrouter import OpenRouterRuntime, RateLimitError

@pytest.fixture
def runtime():
    config = {
        "openrouter_api_key": "test-key",
        "max_concurrent_requests": 2,
        "max_retries": 2,
    }
    return OpenRouterRuntime(config)

@pytest.mark.asyncio
async def test_complete_success(runtime):
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value.json.return_value = {
            "choices": [{"message": {"content": "test response"}}]
        }
        result = await runtime.complete("meta", "test prompt")
        assert result == "test response"

@pytest.mark.asyncio
async def test_rate_limit_retry(runtime):
    with patch("httpx.AsyncClient.post") as mock_post:
        # First call: 429, second call: success
        mock_post.side_effect = [
            httpx.HTTPStatusError("Rate limited", response=MagicMock(status_code=429)),
            MagicMock(json=lambda: {"choices": [{"message": {"content": "ok"}}]}),
        ]
        result = await runtime.complete("meta", "test prompt")
        assert result == "ok"  # succeeded on retry

@pytest.mark.asyncio
async def test_daily_limit_exceeded(runtime):
    runtime._daily_count = 1000  # simulate maxed daily limit
    with pytest.raises(RateLimitError):
        await runtime.complete("meta", "test prompt")
```

---

## 8. Migration from Ollama

If you're migrating an existing Ollama-based setup:

1. **Update dependencies:**
   ```bash
   pip install httpx  # for OpenRouter API calls
   # Optionally remove ollama dependency if no longer needed for completions
   ```

2. **Update `.env`:**
   ```bash
   # Add
   OPENROUTER_API_KEY=sk-or-v1-...
   
   # Keep (if using Ollama for embeddings)
   OLLAMA_HOST=http://localhost:11434
   ```

3. **Update `config/settings.toml`** as shown in §1.2

4. **Replace `llm/ollama.py` with `llm/openrouter.py`** (this doc's implementation)

5. **Update imports** in agents/skills:
   ```python
   # Old
   from src.llm.ollama import OllamaRuntime
   
   # New
   from src.llm.openrouter import OpenRouterRuntime
   ```

6. **Test each agent** with the new runtime, starting with Meta Agent (lightest load)

7. **Monitor usage** closely for the first few days to ensure you stay within free tier limits

---

## 9. Troubleshooting

| Issue | Solution |
|-------|----------|
| **429 Rate Limit errors** | Reduce `max_concurrent_requests`; increase delay between scheduled loops; check actual free tier limits on openrouter.ai |
| **Slow responses** | Increase `request_timeout`; check network latency to OpenRouter; consider reducing `max_tokens` for simple tasks |
| **Model not found** | Verify model string format (`provider/model-name:free`); check model availability on openrouter.ai/models |
| **Embedding failures** | Ensure Ollama is running (if using Ollama for embeddings) or sentence-transformers is installed |
| **High token usage** | Reduce prompt lengths; use `meta` role (often sufficient) instead of `reasoning` for simple tasks; enable prompt caching if available |

---

## Related

- [05-meta-agent-and-skills.md](05-meta-agent-and-skills.md) — agents that use the LLM runtime
- [../personal-assistant.implementation.md](../personal-assistant.implementation.md) — configuration
- [../personal-assistant.plans.md](../personal-assistant.plans.md) — D1 foundational decision
- https://openrouter.ai/docs — official OpenRouter documentation
