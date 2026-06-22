"""Tests for the Brainstorming Agent: tools, graph loop, and public API."""

import json
import os
import tempfile

import pytest
from langchain_core.messages import AIMessage

from src.agents.brainstorming.agent import BrainstormingAgent
from src.agents.brainstorming.tools import (
    ToolDeps,
    TurnContext,
    get_available_tools,
    register_interest_directly,
)
from src.store.knowledge import UnifiedKnowledgeStore


# ========== Fixtures ==========

@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
async def store(temp_db):
    s = UnifiedKnowledgeStore(temp_db)
    await s.initialize()
    yield s
    await s.close()


class FakeReasoningLLM:
    """Mimics OpenRouterRuntime.chat() with queued canned text responses."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[str] = []

    async def chat(self, messages, model_role: str = "meta", **kwargs):
        self.calls.append(messages[-1]["content"])
        content = self._responses.pop(0) if self._responses else ""

        class Response:
            pass

        response = Response()
        response.content = content
        return response


class FakeToolCallingChatModel:
    """Duck-typed stand-in for ChatOpenAI: only bind_tools() + ainvoke() are used."""

    def __init__(self, responses: list[AIMessage]):
        self._responses = list(responses)

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        if self._responses:
            return self._responses.pop(0)
        return AIMessage(content="(no more fake responses)")


def make_tool_deps(store, llm=None, user_id="test-user", thread_id="thread-1") -> ToolDeps:
    return ToolDeps(
        store=store,
        llm=llm or FakeReasoningLLM([]),
        user_id=user_id,
        thread_id=thread_id,
        turn=TurnContext(),
        tavily_api_key=None,
    )


# ========== Tool unit tests ==========

@pytest.mark.asyncio
async def test_register_interest_writes_to_store_with_strength_policy(store):
    deps = make_tool_deps(store)
    result = await register_interest_directly(deps, "rust async runtimes", source="explicit")

    assert "rust async runtimes" in result
    strength = await store.get_strength("rust async runtimes")
    assert strength == pytest.approx(0.85, abs=0.01)
    assert "rust async runtimes" in deps.turn.registered_interests


@pytest.mark.asyncio
async def test_register_interest_strength_by_source(store):
    deps = make_tool_deps(store)
    await register_interest_directly(deps, "topic-a", source="conversation")
    await register_interest_directly(deps, "topic-b", source="web_search")

    assert await store.get_strength("topic-a") == pytest.approx(0.55, abs=0.01)
    assert await store.get_strength("topic-b") == pytest.approx(0.50, abs=0.01)


@pytest.mark.asyncio
async def test_web_search_without_api_key_returns_graceful_message(store):
    deps = make_tool_deps(store)
    tools = {t.name: t for t in get_available_tools(deps)}
    result = await tools["web_search"].ainvoke({"query": "rust"})
    assert "unavailable" in result.lower()


@pytest.mark.asyncio
async def test_register_knowledge_links_concepts(store):
    deps = make_tool_deps(store)
    tools = {t.name: t for t in get_available_tools(deps)}
    result = await tools["register_knowledge"].ainvoke(
        {
            "title": "Rust async runtimes overview",
            "summary": "Tokio is the dominant async runtime.",
            "concepts": ["rust", "tokio"],
        }
    )
    assert "Registered knowledge" in result

    concepts = await store.find_concepts_by_label("tokio")
    assert len(concepts) == 1


@pytest.mark.asyncio
async def test_search_knowledge_base_finds_stored_entries(store):
    await store.store_knowledge_entry(
        entry_id="ka-1",
        question="What is Rust ownership?",
        answer="Rust ownership is a memory management model with no garbage collector.",
        quality_score=0.9,
        user_id="cli",
    )
    deps = make_tool_deps(store)
    tools = {t.name: t for t in get_available_tools(deps)}
    result = await tools["search_knowledge_base"].ainvoke({"query": "ownership"})
    assert "ownership" in result.lower()


# ========== Full graph loop tests (via BrainstormingAgent.answer()) ==========

@pytest.mark.asyncio
async def test_answer_runs_one_turn_no_tool_calls(store):
    """intake -> safety(ALLOW) -> assistant(no tool_calls) -> critique(accept) -> register_interest -> END."""
    chat_llm = FakeToolCallingChatModel(
        [AIMessage(content="Here are some brainstorming ideas about rust.")]
    )
    reasoning_llm = FakeReasoningLLM(
        [
            "ALLOW",
            json.dumps({"score": 0.9, "needs_more": False, "notes": "good"}),
            json.dumps({"topics": []}),
        ]
    )

    agent = BrainstormingAgent(store=store, llm=reasoning_llm, config={}, chat_llm=chat_llm)
    result = await agent.answer("Let's brainstorm about rust", user_id="cli")

    assert "rust" in result.text.lower()
    assert result.citations == []


@pytest.mark.asyncio
async def test_answer_executes_tool_call_then_finishes(store):
    """assistant calls register_interest -> tools -> assistant(final) -> critique -> register_interest -> END."""
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "register_interest",
                "args": {"topic": "rust", "source": "explicit"},
                "id": "call_1",
            }
        ],
    )
    final_msg = AIMessage(content="Got it, I've noted your interest in Rust.")

    chat_llm = FakeToolCallingChatModel([tool_call_msg, final_msg])
    reasoning_llm = FakeReasoningLLM(
        [
            "ALLOW",
            json.dumps({"score": 0.9, "needs_more": False, "notes": "good"}),
            json.dumps({"topics": []}),
        ]
    )

    agent = BrainstormingAgent(store=store, llm=reasoning_llm, config={}, chat_llm=chat_llm)
    result = await agent.answer("I'm really interested in rust lately", user_id="cli")

    assert "rust" in result.text.lower()
    strength = await store.get_strength("rust")
    assert strength == pytest.approx(0.85, abs=0.01)


@pytest.mark.asyncio
async def test_safety_blocks_disallowed_query(store):
    chat_llm = FakeToolCallingChatModel([AIMessage(content="should never be called")])
    reasoning_llm = FakeReasoningLLM(["BLOCK"])

    agent = BrainstormingAgent(store=store, llm=reasoning_llm, config={}, chat_llm=chat_llm)
    result = await agent.answer("some disallowed request", user_id="cli")

    assert "can't help" in result.text.lower()


@pytest.mark.asyncio
async def test_critique_loop_respects_max_iterations(store):
    """If critique keeps asking for more, the loop must still stop at max_iterations."""
    chat_llm = FakeToolCallingChatModel(
        [AIMessage(content="draft 1"), AIMessage(content="draft 2 (final)")]
    )
    # Consumption order: safety(ALLOW), critique call #1 (iteration 1 < max 2 -> needs_more),
    # critique call #2 short-circuits on the max_iterations check (no LLM call), register_interest.
    reasoning_llm = FakeReasoningLLM(
        [
            "ALLOW",
            json.dumps({"score": 0.3, "needs_more": True, "notes": "more"}),
            json.dumps({"topics": []}),
        ]
    )

    config = {"agents": {"brainstorming": {"max_iterations": 2}}}
    agent = BrainstormingAgent(store=store, llm=reasoning_llm, config=config, chat_llm=chat_llm)
    result = await agent.answer("keep improving this", user_id="cli")

    assert result.text == "draft 2 (final)"
