"""Assistant node: binds this turn's tools to the chat model and takes one step."""

import logging

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI

from ..state import BrainstormingState
from ..tools import ToolDeps, get_available_tools

logger = logging.getLogger(__name__)


async def assistant_node(
    state: BrainstormingState, llm: ChatOpenAI, deps: ToolDeps, system_prompt: str
) -> dict:
    tools = get_available_tools(deps)
    bound_llm = llm.bind_tools(tools)

    messages = [SystemMessage(content=system_prompt), *state["messages"]]
    response = await bound_llm.ainvoke(messages)

    # Log tool calls if any
    if hasattr(response, "tool_calls") and response.tool_calls:
        for tc in response.tool_calls:
            tool_name = tc.get("name", "unknown")
            logger.info(f"[Node] Assistant calling tool: {tool_name}")
    else:
        logger.info("[Node] Assistant generated response (no tools called)")

    return {"messages": [response], "iteration": state["iteration"] + 1}
