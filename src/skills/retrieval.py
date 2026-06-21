"""Retrieval skill - hybrid knowledge retrieval."""

from typing import Any

from ..store.vector import KnowledgeBase, Hit


async def retrieve_knowledge(
    query: str,
    kb: KnowledgeBase,
    k: int = 8,
    topic_filter: str | None = None,
) -> list[Hit]:
    """
    Retrieve relevant knowledge from the knowledge base.

    Args:
        query: Search query
        kb: KnowledgeBase instance
        k: Number of results to return
        topic_filter: Optional topic to filter by

    Returns:
        List of hits sorted by relevance
    """
    # Perform semantic search
    hits = await kb.search(query, k=k * 2)  # Get more for filtering

    # Apply topic filter if specified
    if topic_filter:
        hits = [h for h in hits if h.chunk.topic == topic_filter]

    # Sort by score and return top k
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:k]


def format_retrieval_context(hits: list[Hit], max_tokens: int = 2000) -> str:
    """
    Format retrieval hits into context for LLM.

    Args:
        hits: List of retrieval hits
        max_tokens: Maximum tokens in context

    Returns:
        Formatted context string
    """
    sections = []
    total_tokens = 0

    for i, hit in enumerate(hits, 1):
        section = f"""[Source {i}] ({hit.chunk.source_url or 'Unknown'})
Topic: {hit.chunk.topic}
Relevance: {hit.score:.2f}

{hit.chunk.text}

---
"""
        # Rough token estimation (4 chars ≈ 1 token)
        section_tokens = len(section) // 4
        if total_tokens + section_tokens > max_tokens:
            break

        sections.append(section)
        total_tokens += section_tokens

    if not sections:
        return "No relevant information found in the knowledge base."

    return "\n".join(sections)
