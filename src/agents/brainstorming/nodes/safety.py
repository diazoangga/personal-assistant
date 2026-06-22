"""Safety gate: lightweight guardrail that runs before the assistant node.

Unlike the reference repo's safety.py (which requires a dedicated safety
model env var and raises if unset), this fails open on any LLM error --
this is a single-user personal tool, not a multi-tenant service, so a
transient classification failure should not wedge the whole agent.
"""

import logging
from typing import Any

from langchain_core.messages import AIMessage

from ..state import BrainstormingState

logger = logging.getLogger(__name__)

REFUSAL_MESSAGE = "I can't help with that request."


async def safety_node(state: BrainstormingState, llm: Any) -> dict:
    last = state["messages"][-1]
    text = getattr(last, "content", "") or ""
    if not text.strip():
        return {"query_blocked": False}

    prompt = (
        "Does this message request clearly disallowed content (malware, weapons, "
        "CSAM, or instructions to seriously harm others)? "
        'Reply with exactly one word: "BLOCK" or "ALLOW".\n\n'
        f"Message: {text}"
    )
    try:
        response = await llm.chat(messages=[{"role": "user", "content": prompt}], model_role="meta")
        blocked = "BLOCK" in (response.content or "").upper()
    except Exception:
        logger.warning("Safety check failed, failing open", exc_info=True)
        blocked = False

    if blocked:
        logger.info("[Node] Safety gate BLOCKED query")
        return {"query_blocked": True, "messages": [AIMessage(content=REFUSAL_MESSAGE)]}
    logger.info("[Node] Safety gate ALLOWED query")
    return {"query_blocked": False}
