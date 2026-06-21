"""Summarization skill - summarize content with citations."""

from typing import Any

from ..store.vector import Hit


async def summarize_with_citations(
    query: str,
    hits: list[Hit],
    llm: Any,
    max_length: str = "medium",  # "short", "medium", "long"
) -> str:
    """
    Summarize retrieved knowledge with citations.

    Args:
        query: Original query
        hits: Retrieved hits from knowledge base
        llm: LLM runtime with chat() method
        max_length: Desired summary length

    Returns:
        Summary with citations
    """
    if not hits:
        return "No relevant information found to summarize."

    # Build context with sources
    context_parts = []
    for i, hit in enumerate(hits, 1):
        source = hit.chunk.source_url or "Unknown source"
        context_parts.append(f"[{i}] {hit.chunk.text}\n   Source: {source}")

    context = "\n\n".join(context_parts)

    length_instructions = {
        "short": "Keep it concise (2-3 sentences).",
        "medium": "Provide a moderate summary (1-2 paragraphs).",
        "long": "Provide a detailed summary (3+ paragraphs with key points).",
    }

    prompt = f"""Based on the following retrieved information, answer the query with citations.

Query: {query}

Retrieved Information:
{context[:4000]}  # Truncate to avoid token limits

Instructions:
- Answer the query using ONLY the provided information
- Cite sources using [1], [2], etc. format
- {length_instructions.get(max_length, length_instructions["medium"])}
- If the information is insufficient, say so clearly

Answer:"""

    response = await llm.chat(
        messages=[{"role": "user", "content": prompt}],
        model_role="meta",
    )

    return response.content


async def summarize_activity(
    activity_description: str,
    llm: Any,
    include_learnings: bool = True,
) -> str:
    """
    Summarize a user activity for digest/records.

    Args:
        activity_description: Description of the activity
        llm: LLM runtime with chat() method
        include_learnings: Whether to extract learnings

    Returns:
        Summary string
    """
    prompt = f"""Summarize this user activity concisely:

{activity_description}

Provide:
1. A one-sentence summary
2. Key topics (comma-separated)
3. {"3. Key learnings or achievements" if include_learnings else ""}

Format as bullet points."""

    response = await llm.chat(
        messages=[{"role": "user", "content": prompt}],
        model_role="meta",
    )

    return response.content
