"""Relation extraction skill — extract typed edges between concepts.

Second LLM pass: given a set of extracted concepts, identify relationships using
a closed vocabulary (uses, extends, competes_with, evaluated_on, part_of, related_to).
Weights are normalized to [0, 1]; edges are deduplicated by (source, target, type).
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Closed vocabulary for concept relationships
RELATION_TYPES = ["uses", "extends", "competes_with", "evaluated_on", "part_of", "related_to"]


@dataclass
class ExtractedRelation:
    """A relationship between two concepts."""

    source: str
    target: str
    relation_type: str  # One of RELATION_TYPES
    weight: float  # [0, 1]
    evidence: str


@dataclass
class RelationExtractionResult:
    """Result of relation extraction from a concept set."""

    relations: list[ExtractedRelation]
    source_id: str


async def extract_relations(
    concept_names: list[str],
    llm: Any,
    source_id: str,
    context: str = "",
) -> RelationExtractionResult:
    """Extract typed relationships between concepts.

    Args:
        concept_names: List of concept names to relate
        llm: LLM runtime with chat() method
        source_id: Citation ID
        context: Additional context about the relationships

    Returns:
        RelationExtractionResult with deduplicated relations
    """
    if len(concept_names) < 2:
        return RelationExtractionResult(relations=[], source_id=source_id)

    concepts_str = ", ".join(concept_names)
    relation_types_str = ", ".join(RELATION_TYPES)

    prompt = f"""Given these concepts, extract relationships between them.

Concepts: {concepts_str}

Allowed relationship types: {relation_types_str}

{f"Context: {context}" if context else ""}

Return ONLY a JSON array:
[
    {{"source": "concept A", "target": "concept B", "relation_type": "uses", "weight": 0.9, "evidence": "brief reason"}}
]

Weight: 0.0 to 1.0 (strength of the relationship).
Do NOT invent concepts not in the list.

Array:"""

    response = await llm.chat(
        messages=[{"role": "user", "content": prompt}],
        model_role="meta",
    )

    raw_relations = _parse_relations(response.content, set(n.lower() for n in concept_names))
    relations = _deduplicate_relations(raw_relations)

    return RelationExtractionResult(relations=relations, source_id=source_id)


def _parse_relations(response_content: str, valid_concepts: set[str]) -> list[ExtractedRelation]:
    """Parse relations from LLM response, validating against known concepts."""
    content = response_content.strip()

    # Strip markdown code blocks
    if content.startswith("```"):
        parts = content.split("```")
        content = parts[1] if len(parts) > 1 else content
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    relations = []
    try:
        data = json.loads(content)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    try:
                        source = (item.get("source") or "").strip()
                        target = (item.get("target") or "").strip()
                        relation_type = (item.get("relation_type") or "").strip().lower()
                        weight = float(item.get("weight") or 0)
                        weight = max(0.0, min(1.0, weight))
                        evidence = (item.get("evidence") or "").strip()

                        # Validate: both concepts must exist and relation type must be known
                        if (
                            source.lower() in valid_concepts
                            and target.lower() in valid_concepts
                            and relation_type in RELATION_TYPES
                        ):
                            relations.append(
                                ExtractedRelation(
                                    source=source,
                                    target=target,
                                    relation_type=relation_type,
                                    weight=weight,
                                    evidence=evidence or relation_type,
                                )
                            )
                    except (ValueError, TypeError):
                        pass
    except json.JSONDecodeError:
        logger.debug("Relation extraction: malformed JSON response")

    return relations


def _deduplicate_relations(relations: list[ExtractedRelation]) -> list[ExtractedRelation]:
    """Deduplicate by (source, target, type), keeping highest weight."""
    deduped = {}
    for r in relations:
        key = (r.source.lower(), r.target.lower(), r.relation_type)
        if key not in deduped or r.weight > deduped[key].weight:
            deduped[key] = r

    return list(deduped.values())
