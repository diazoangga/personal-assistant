"""Public API for the Brainstorming Agent.

Wraps the LangGraph StateGraph (graph.py) behind the .answer()/.run_session()
methods that core/engine.py already expects from whatever is registered
under the "brainstorm" agent name.
"""

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from langchain_openai import ChatOpenAI

from ...core.events import Message, Result
from ...store.knowledge import UnifiedKnowledgeStore
from .graph import build_graph
from .state import initial_state
from .tools import ToolDeps, TurnContext

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system_prompt.txt").read_text(encoding="utf-8")


@dataclass
class BrainstormAnswer:
    text: str
    citations: list[str] = field(default_factory=list)


class BrainstormingAgent:
    """LangGraph-backed agent implementing the 9 brainstorming capabilities."""

    def __init__(
        self,
        store: UnifiedKnowledgeStore,
        llm: Any,
        config: dict[str, Any],
        chat_llm: Optional[Any] = None,
    ):
        self.store = store
        self.reasoning_llm = llm  # OpenRouterRuntime, shared with the rest of the engine

        llm_config = config.get("llm", {})
        brainstorm_config = config.get("agents", {}).get("brainstorming", {})

        self.max_iterations = brainstorm_config.get("max_iterations", 5)
        self.tavily_api_key = config.get("tavily_api_key") or None

        if chat_llm is not None:
            # Test seam: inject a fake tool-calling chat model instead of hitting OpenRouter.
            self.chat_llm = chat_llm
        else:
            model_name = brainstorm_config.get("model") or llm_config.get(
                "meta_model", "google/gemma-4-26b-a4b-it:free"
            )
            self.chat_llm = ChatOpenAI(
                base_url=llm_config.get("base_url", "https://openrouter.ai/api/v1"),
                api_key=config.get("openrouter_api_key", ""),
                model=model_name,
                temperature=brainstorm_config.get("temperature", 0.7),
            )

    def _build_deps(self, user_id: str, thread_id: str) -> ToolDeps:
        return ToolDeps(
            store=self.store,
            llm=self.reasoning_llm,
            user_id=user_id,
            thread_id=thread_id,
            turn=TurnContext(),
            tavily_api_key=self.tavily_api_key,
        )

    async def answer(
        self, query: str, user_id: str = "cli", thread_id: Optional[str] = None
    ) -> BrainstormAnswer:
        """One-shot Q&A entry point, used by core/engine.py::_handle_ask."""
        thread_id = thread_id or f"ask-{uuid.uuid4().hex[:8]}"
        deps = self._build_deps(user_id, thread_id)
        graph = build_graph(self.chat_llm, self.reasoning_llm, deps, _SYSTEM_PROMPT)

        state = initial_state(
            query, user_id=user_id, thread_id=thread_id, max_iterations=self.max_iterations
        )
        final_state = await graph.ainvoke(state)

        text = _last_text(final_state)
        citations = [f"{s.get('title', '')} ({s.get('url', '')})" for s in deps.turn.gathered_sources]
        return BrainstormAnswer(text=text, citations=citations)

    async def run_session(self, job_id: str, cmd: Any, publish: Any) -> None:
        """Interactive session entry point, used by core/engine.py::_handle_brainstorm."""
        user_id = getattr(cmd, "user", "cli")
        thread_id = getattr(cmd, "session_id", None) or f"brainstorm-{job_id}"
        text_in = getattr(cmd, "text", "")

        deps = self._build_deps(user_id, thread_id)
        graph = build_graph(self.chat_llm, self.reasoning_llm, deps, _SYSTEM_PROMPT)

        state = initial_state(
            text_in, user_id=user_id, thread_id=thread_id, max_iterations=self.max_iterations
        )
        final_state = await graph.ainvoke(state)

        text = _last_text(final_state)
        citations = [f"{s.get('title', '')} ({s.get('url', '')})" for s in deps.turn.gathered_sources]
        await publish(Message(job_id=job_id, role="assistant", text=text, citations=citations))
        await publish(Result(job_id=job_id, ok=True, payload={"answer": text}))


def _last_text(state: dict) -> str:
    for m in reversed(state["messages"]):
        content = getattr(m, "content", None)
        if content:
            return content
    return ""
