"""Paper synthesis skill — LLM-generated conclusion and notes from abstract+tldr.

Locked to abstract-level analysis (no PDF parsing). Output is stored in the
citations table's `conclusion` and `notes` (JSON-encoded dict with
key_contributions, methods, limitations).
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SynthesizedPaper:
    """Synthesized higher-level understanding of a paper."""

    conclusion: str
    notes: dict[str, Any]  # {"key_contributions": [...], "methods": [...], "limitations": [...]}
    source_id: str


async def synthesize_paper(
    title: str,
    abstract: str,
    tldr: str,
    llm: Any,
    source_id: str,
) -> SynthesizedPaper:
    """Synthesize conclusion and notes from abstract+tldr (no full-text parsing).

    Args:
        title: Paper title
        abstract: Paper abstract
        tldr: Semantic Scholar tldr (if available)
        llm: LLM runtime with chat() method
        source_id: Citation ID

    Returns:
        SynthesizedPaper with conclusion and structured notes
    """
    combined = f"Title: {title}\n\n"
    if abstract:
        combined += f"Abstract:\n{abstract}\n\n"
    if tldr:
        combined += f"TLDR:\n{tldr}\n\n"

    prompt = f"""Analyze this paper and synthesize key insights. Use ONLY the provided text.

{combined}

Return ONLY a JSON object:
{{
    "conclusion": "One paragraph summarizing the paper's main contribution and significance.",
    "notes": {{
        "key_contributions": ["bullet", "bullet"],
        "methods": ["bullet", "bullet"],
        "limitations": ["bullet", "bullet"]
    }}
}}

No markdown, no code blocks, just JSON.

Object:"""

    response = await llm.chat(
        messages=[{"role": "user", "content": prompt}],
        model_role="meta",
    )

    result = _parse_synthesis(response.content)
    return SynthesizedPaper(
        conclusion=result.get("conclusion", ""),
        notes=result.get("notes", {"key_contributions": [], "methods": [], "limitations": []}),
        source_id=source_id,
    )


def _parse_synthesis(response_content: str) -> dict[str, Any]:
    """Parse synthesis result from LLM response, with graceful fallback."""
    content = response_content.strip()

    # Strip markdown code blocks
    if content.startswith("```"):
        parts = content.split("```")
        content = parts[1] if len(parts) > 1 else content
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    try:
        data = json.loads(content)
        if isinstance(data, dict):
            conclusion = (data.get("conclusion") or "").strip()
            notes = data.get("notes") or {}

            # Validate/normalize notes structure
            if not isinstance(notes, dict):
                notes = {}
            for key in ["key_contributions", "methods", "limitations"]:
                if key not in notes:
                    notes[key] = []
                elif not isinstance(notes[key], list):
                    notes[key] = []

            if conclusion:
                return {"conclusion": conclusion, "notes": notes}

    except json.JSONDecodeError:
        logger.debug("Paper synthesis: malformed JSON response")

    # Fallback: empty synthesis
    return {
        "conclusion": "",
        "notes": {"key_contributions": [], "methods": [], "limitations": []},
    }
