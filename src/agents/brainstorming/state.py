"""State schema for the Brainstorming Agent's LangGraph StateGraph."""

from typing import Annotated, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class BrainstormingState(TypedDict):
    """Per-turn/per-thread state for the self-supervising brainstorming loop.

    Working-memory bookkeeping (gathered sources, registered interests) is kept
    out of this checkpointed state on purpose -- it lives in the per-turn
    TurnContext (see agent.py) so tools can mutate it directly via closure
    without needing LangGraph's Command/state-update machinery.
    """

    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str
    thread_id: str

    # control
    iteration: int
    max_iterations: int
    should_end: bool
    query_blocked: bool
    needs_more: bool

    # critique
    critique_score: Optional[float]
    critique_notes: Optional[str]

    error: Optional[str]


def initial_state(
    user_input: str,
    user_id: str = "cli",
    thread_id: str = "default",
    max_iterations: int = 5,
) -> BrainstormingState:
    """Build the initial state for a new turn."""
    from langchain_core.messages import HumanMessage

    return BrainstormingState(
        messages=[HumanMessage(content=user_input)],
        user_id=user_id,
        thread_id=thread_id,
        iteration=0,
        max_iterations=max_iterations,
        should_end=False,
        query_blocked=False,
        needs_more=False,
        critique_score=None,
        critique_notes=None,
        error=None,
    )
