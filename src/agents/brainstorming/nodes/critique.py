"""Self-critique node: LLM-as-judge decides whether the turn needs another pass."""

import json
import logging
from typing import Any

from ..state import BrainstormingState

logger = logging.getLogger(__name__)


async def critique_node(state: BrainstormingState, llm: Any) -> dict:
    if state["iteration"] >= state["max_iterations"]:
        return {
            "needs_more": False,
            "critique_score": state.get("critique_score") or 0.5,
            "critique_notes": "Stopped: reached max iterations.",
        }

    transcript = _render_transcript(state)
    prompt = f"""Review this assistant's response to the user's request.

{transcript}

Rate the response's completeness and usefulness from 0.0 to 1.0, and decide if
it needs another pass (more tool calls/research) before it's ready to show the
user. Reply as JSON: {{"score": <float>, "needs_more": <bool>, "notes": "<short reason>"}}"""

    try:
        response = await llm.chat(messages=[{"role": "user", "content": prompt}], model_role="meta")
        data = json.loads(_extract_json(response.content))
        score = float(data.get("score", 0.7))
        needs_more = bool(data.get("needs_more", False))
        notes = str(data.get("notes", ""))
    except Exception:
        logger.warning("Critique parsing failed, accepting response as-is", exc_info=True)
        score, needs_more, notes = 0.7, False, "Critique unavailable; accepted as-is."

    if needs_more:
        logger.info(f"[Node] Critique: needs more work (score={score:.2f})")
    else:
        logger.info(f"[Node] Critique: response accepted (score={score:.2f})")

    return {"critique_score": score, "needs_more": needs_more, "critique_notes": notes}


def _render_transcript(state: BrainstormingState) -> str:
    lines = []
    for m in state["messages"][-6:]:
        role = getattr(m, "type", "unknown")
        content = getattr(m, "content", "")
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _extract_json(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in critique response")
    return text[start : end + 1]
