"""Wraps langgraph.prebuilt.ToolNode for this turn's bound tool instances.

The reference repo's tools_executor.py wraps ToolNode to auto-inject user_id
into tool args and translate ToolException into user-facing messages. Here,
user_id/thread_id are already baked into the tools via the closed-over
ToolDeps (see tools.py), so this wrapper only needs to rebuild the tool list
and delegate -- LangChain's StructuredTool already turns exceptions raised
inside a tool into a ToolMessage(status="error") rather than crashing the run.
"""

from langgraph.prebuilt import ToolNode

from ..state import BrainstormingState
from ..tools import ToolDeps, get_available_tools


async def tools_executor_node(state: BrainstormingState, deps: ToolDeps) -> dict:
    tools = get_available_tools(deps)
    node = ToolNode(tools)
    return await node.ainvoke(state)
