"""End-of-turn node: auto-register interests implied by the conversation.

This is what makes interest registration happen even when the user never
explicitly says "I'm interested in X" and the assistant never calls the
register_interest tool itself -- it covers the "infer from conversation"
half of the requirement (web_search/github signals are covered by other
agents' existing pipelines).
"""

import json
import logging
from typing import Any

from ..state import BrainstormingState
from ..tools import ToolDeps, register_interest_directly

logger = logging.getLogger(__name__)


async def register_interest_node(state: BrainstormingState, llm: Any, deps: ToolDeps) -> dict:
    transcript = "\n".join(
        f"{getattr(m, 'type', '?')}: {getattr(m, 'content', '')}"
        for m in state["messages"]
        if getattr(m, "content", None)
    )[-4000:]

    prompt = f"""From this brainstorming conversation, list up to 3 topics the
user has shown genuine interest in (not already obviously covered). Reply as
JSON: {{"topics": ["topic1", "topic2"]}}. If none, reply {{"topics": []}}.

Conversation:
{transcript}"""

    topics: list[str] = []
    try:
        response = await llm.chat(messages=[{"role": "user", "content": prompt}], model_role="meta")
        start, end = response.content.find("{"), response.content.rfind("}")
        data = json.loads(response.content[start : end + 1])
        topics = [t.strip().lower() for t in data.get("topics", []) if t.strip()]
    except Exception:
        logger.warning("Interest extraction failed", exc_info=True)

    if topics:
        logger.info(f"[Node] Registering {len(topics)} inferred interests: {', '.join(topics)}")
        for topic in topics:
            if topic in deps.turn.registered_interests:
                continue
            await register_interest_directly(deps, topic, source="conversation")
    else:
        logger.info("[Node] No interests inferred from conversation")

    return {}
