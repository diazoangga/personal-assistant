"""StateGraph wiring: intake -> safety -> assistant <-> tools -> critique -> register_interest -> END.

Built fresh per turn (via build_graph) rather than compiled once as a
singleton, because nodes are closures over this turn's ToolDeps/TurnContext
-- compiling a handful of nodes is cheap and keeps user/thread scoping
trivially correct without threading non-serializable deps through the
checkpointed state.
"""

from typing import Any, Literal

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from .nodes.assistant import assistant_node
from .nodes.critique import critique_node
from .nodes.intake import intake_node
from .nodes.register_interest import register_interest_node
from .nodes.safety import safety_node
from .nodes.tools_executor import tools_executor_node
from .state import BrainstormingState
from .tools import ToolDeps


def build_graph(llm: ChatOpenAI, reasoning_llm: Any, deps: ToolDeps, system_prompt: str):
    """Compile the brainstorming StateGraph for a single turn.

    llm: LangChain ChatOpenAI used for tool-calling (assistant node).
    reasoning_llm: OpenRouterRuntime used for plain-text judgment calls
        (safety, critique, interest extraction) that don't need tool calling.
    """

    async def _intake(state: BrainstormingState) -> dict:
        return await intake_node(state)

    async def _safety(state: BrainstormingState) -> dict:
        return await safety_node(state, reasoning_llm)

    async def _assistant(state: BrainstormingState) -> dict:
        return await assistant_node(state, llm, deps, system_prompt)

    async def _tools(state: BrainstormingState) -> dict:
        return await tools_executor_node(state, deps)

    async def _critique(state: BrainstormingState) -> dict:
        return await critique_node(state, reasoning_llm)

    async def _register_interest(state: BrainstormingState) -> dict:
        return await register_interest_node(state, reasoning_llm, deps)

    def _route_after_safety(state: BrainstormingState) -> Literal["assistant", "__end__"]:
        return END if state["query_blocked"] else "assistant"

    def _route_after_assistant(state: BrainstormingState) -> Literal["tools", "critique"]:
        last = state["messages"][-1]
        tool_calls = getattr(last, "tool_calls", None)
        return "tools" if tool_calls else "critique"

    def _route_after_critique(state: BrainstormingState) -> Literal["assistant", "register_interest"]:
        if state["needs_more"] and state["iteration"] < state["max_iterations"]:
            return "assistant"
        return "register_interest"

    workflow = StateGraph(BrainstormingState)
    workflow.add_node("intake", _intake)
    workflow.add_node("safety", _safety)
    workflow.add_node("assistant", _assistant)
    workflow.add_node("tools", _tools)
    workflow.add_node("critique", _critique)
    workflow.add_node("register_interest", _register_interest)

    workflow.add_edge(START, "intake")
    workflow.add_edge("intake", "safety")
    workflow.add_conditional_edges("safety", _route_after_safety, {"assistant": "assistant", END: END})
    workflow.add_conditional_edges(
        "assistant", _route_after_assistant, {"tools": "tools", "critique": "critique"}
    )
    workflow.add_edge("tools", "assistant")
    workflow.add_conditional_edges(
        "critique",
        _route_after_critique,
        {"assistant": "assistant", "register_interest": "register_interest"},
    )
    workflow.add_edge("register_interest", END)

    return workflow.compile()
