"""Entity extraction skill — extract typed concepts from paper abstracts.

Adapted from prior research-agent design: produces concept nodes for the knowledge
graph (G3 in data-model.md). Filters by confidence threshold; deduplicates by
(name, category) keeping highest-confidence.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ExtractedEntity:
    """An extracted concept with type and confidence."""

    name: str
    category: str  # concept, method, task, dataset, metric, model, framework
    description: str
    confidence: float


@dataclass
class EntityExtractionResult:
    """Result of entity extraction from a paper abstract."""

    entities: list[ExtractedEntity]
    source_id: str


async def extract_entities(
    text: str,
    llm: Any,
    source_id: str,
    max_entities: int = 20,
    min_confidence: float = 0.6,
) -> EntityExtractionResult:
    """Extract typed concepts from text (e.g., paper abstract).

    Args:
        text: Input text (truncated to 2000 chars)
        llm: LLM runtime with chat() method
        source_id: Citation ID
        max_entities: Max concepts to return
        min_confidence: Drop entities below this threshold

    Returns:
        EntityExtractionResult with filtered, deduplicated entities
    """
    categories = ["concept", "method", "task", "dataset", "metric", "model", "framework"]
    categories_str = ", ".join(categories)

    prompt = f"""Extract key research concepts and entities from this text.

Allowed types: {categories_str}

Return ONLY a JSON array (no markdown, no extra text):
[
    {{"name": "entity", "category": "type", "description": "1-2 sentences", "confidence": 0.95}}
]

Up to {max_entities} entities. Confidence: 0.0 to 1.0.

Text:
{text[:2000]}

Array:"""

    response = await llm.chat(
        messages=[{"role": "user", "content": prompt}],
        model_role="meta",
    )

    raw_entities = _parse_entities(response.content)
    entities = [e for e in raw_entities if e.confidence >= min_confidence]

    # Deduplicate by (name, category), keeping highest confidence
    deduped = {}
    for e in entities:
        key = (e.name.lower(), e.category.lower())
        if key not in deduped or e.confidence > deduped[key].confidence:
            deduped[key] = e

    return EntityExtractionResult(entities=list(deduped.values()), source_id=source_id)


def _parse_entities(response_content: str) -> list[ExtractedEntity]:
    """Parse entities from LLM response, tolerating malformed JSON."""
    content = response_content.strip()

    # Strip markdown code blocks if present
    if content.startswith("```"):
        parts = content.split("```")
        content = parts[1] if len(parts) > 1 else content
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    entities = []
    try:
        data = json.loads(content)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    try:
                        name = (item.get("name") or "").strip()
                        category = (item.get("category") or "").strip().lower()
                        description = (item.get("description") or "").strip()
                        confidence = float(item.get("confidence") or 0)
                        confidence = max(0.0, min(1.0, confidence))

                        if name and category:
                            entities.append(
                                ExtractedEntity(
                                    name=name,
                                    category=category,
                                    description=description or name,
                                    confidence=confidence,
                                )
                            )
                    except (ValueError, TypeError):
                        pass
    except json.JSONDecodeError:
        logger.debug("Entity extraction: malformed JSON response")

    return entities
