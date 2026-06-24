"""OpenRouter LLM runtime with Gemma-4-26b free tier."""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class RateLimitError(Exception):
    """Raised when OpenRouter free tier rate limits are exceeded."""

    message: str


@dataclass
class APIError(Exception):
    """Raised on OpenRouter API failures."""

    message: str
    status_code: int | None = None


class OpenRouterRuntime:
    """
    OpenRouter API client for LLM completions and embeddings.

    Uses Gemma-4-26b free tier for LLM and Qwen3-embedding-8b for embeddings.
    """

    def __init__(self, config: dict[str, Any]):
        self.api_key = config.get("openrouter_api_key", "")

        # Get LLM config section
        llm_config = config.get("llm", {})
        self.base_url = llm_config.get("base_url", "https://openrouter.ai/api/v1")
        self.max_concurrent = llm_config.get("rate_limit_per_minute", 60) // 60
        self.timeout = config.get("request_timeout", 60)
        self.max_retries = llm_config.get("max_retries", 3)

        # Rate limiting
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        self._request_times: list[float] = []
        self._daily_count = 0
        self._daily_reset = time.time() + 86400

        # Model routing from settings
        self.role_models = {
            "meta": llm_config.get("meta_model", "google/gemma-4-26b-a4b-it:free"),
            "reasoning": llm_config.get("reasoning_model", "google/gemma-4-26b-a4b-it:free"),
        }
        self.embedding_model = llm_config.get("embedding_model", "qwen/qwen3-embedding-8b")

    async def chat(self, messages: list[dict[str, str]], model_role: str = "meta", **kwargs: Any) -> Any:
        """
        Chat interface (compatible with other LLM runtimes).

        Args:
            messages: List of message dicts with 'role' and 'content' keys
            model_role: Which model to use ("meta" or "reasoning")
            **kwargs: Additional parameters (max_tokens, temperature, etc.)

        Returns:
            Response object with .content attribute
        """
        # Convert messages to a prompt
        prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
        content = await self.complete(model_role, prompt, **kwargs)

        # Return a simple response object
        class Response:
            def __init__(self, content: str):
                self.content = content

        return Response(content)

    async def complete(self, role: str, prompt: str, **kwargs: Any) -> str:
        """
        Make a completion request to OpenRouter.

        Args:
            role: "meta" or "reasoning" - determines which model to use
            prompt: The full prompt text
            **kwargs: max_tokens, temperature, etc.

        Returns:
            The completion text

        Raises:
            RateLimitError: If free tier limits are exceeded
            APIError: On API failures
        """
        model = self.role_models.get(role, self.role_models["meta"])
        logger.debug(f"Making completion request with model: {model}")

        async with self._semaphore:
            await self._check_rate_limits()

            for attempt in range(self.max_retries):
                try:
                    logger.debug(f"Completion attempt {attempt + 1}/{self.max_retries}")
                    result = await self._make_request(model, prompt, **kwargs)
                    logger.debug("Completion request successful")
                    return result
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429 and attempt < self.max_retries - 1:
                        wait_time = (2**attempt) * 2
                        logger.warning(f"Rate limited, waiting {wait_time}s before retry")
                        await asyncio.sleep(wait_time)
                        continue
                    logger.error(f"HTTP error {e.response.status_code}: {e}", exc_info=True)
                    raise APIError(f"HTTP error: {e}", status_code=e.response.status_code)
                except Exception as e:
                    if attempt < self.max_retries - 1:
                        logger.warning(f"Request failed, retrying in {2**attempt}s: {e}")
                        await asyncio.sleep(2**attempt)
                        continue
                    logger.error(f"Request failed after {attempt + 1} attempts: {e}", exc_info=True)
                    raise APIError(f"Request failed: {e}")

        logger.error(f"Failed after {self.max_retries} retries")
        raise APIError(f"Failed after {self.max_retries} retries")

    async def _make_request(self, model: str, prompt: str, **kwargs: Any) -> str:
        """Low-level API call."""
        max_tokens = kwargs.get("max_tokens", 2048)
        temperature = kwargs.get("temperature", 0.7)

        logger.debug(f"Sending request to {model} (max_tokens={max_tokens}, temperature={temperature})")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/personal-assistant",
            "X-Title": "Personal Assistant",
        }

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            logger.debug(f"POST {self.base_url}/chat/completions")
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )

            if response.status_code != 200:
                logger.error(f"API returned status {response.status_code}: {response.text[:200]}")
                raise httpx.HTTPStatusError(
                    f"API error: {response.status_code}",
                    request=response.request,
                    response=response,
                )

            data = response.json()
            content = data["choices"][0]["message"]["content"]
            logger.debug(f"Received response ({len(content)} chars)")
            return content

    async def _check_rate_limits(self) -> None:
        """Check and enforce rate limits before making a request."""
        now = time.time()

        # Reset daily counter if needed
        if now > self._daily_reset:
            self._daily_count = 0
            self._daily_reset = now + 86400

        # Check daily limit (approximate - adjust based on actual free tier)
        if self._daily_count >= 1000:
            raise RateLimitError("Daily request limit exceeded")

        # Check per-minute limit
        self._request_times = [t for t in self._request_times if now - t < 60]
        if len(self._request_times) >= 60:  # ~60 requests per minute
            wait_time = 60 - (now - self._request_times[0])
            if wait_time > 0:
                await asyncio.sleep(wait_time)

        self._request_times.append(now)
        self._daily_count += 1

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings using OpenRouter API.

        Uses Qwen3-embedding-8b for cost-effective embeddings.
        """
        logger.debug(f"Generating embeddings for {len(texts)} text(s)")
        
        async with self._semaphore:
            await self._check_rate_limits()

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/personal-assistant",
                "X-Title": "Personal Assistant",
            }

            payload = {
                "model": self.embedding_model,
                "input": texts,
            }

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                logger.debug("Sending embedding request")
                response = await client.post(
                    f"{self.base_url}/embeddings",
                    headers=headers,
                    json=payload,
                )

                if response.status_code != 200:
                    logger.error(f"Embedding API error: {response.status_code} - {response.text[:200]}")
                    raise APIError(
                        f"Embedding API error: {response.text}",
                        status_code=response.status_code,
                    )

                data = response.json()
                embeddings = [item["embedding"] for item in data["data"]]
                logger.debug(f"Generated {len(embeddings)} embeddings")
                return embeddings

    def get_usage_stats(self) -> dict[str, Any]:
        """Return current usage statistics."""
        now = time.time()
        requests_last_minute = len([t for t in self._request_times if now - t < 60])

        return {
            "requests_this_minute": requests_last_minute,
            "requests_today": self._daily_count,
            "daily_reset_in_hours": (self._daily_reset - now) / 3600,
            "concurrent_requests": self.max_concurrent - self._semaphore._value,
        }
