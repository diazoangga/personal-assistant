"""Topic extraction skill - extract topics from text."""

from typing import Any


async def extract_topics(text: str, llm: Any, max_topics: int = 5) -> list[str]:
    """
    Extract key topics from text using LLM.

    Args:
        text: Input text to analyze
        llm: LLM runtime with chat() method
        max_topics: Maximum number of topics to extract

    Returns:
        List of topic strings
    """
    prompt = f"""Extract {max_topics} key topics from the following text. 
Return only a JSON array of topic strings, nothing else.

Text:
{text[:2000]}  # Truncate to avoid token limits

Topics:"""

    response = await llm.chat(
        messages=[{"role": "user", "content": prompt}],
        model_role="meta",
    )

    # Parse JSON array from response
    import json

    content = response.content.strip()
    # Remove markdown code blocks if present
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    try:
        topics = json.loads(content)
        if isinstance(topics, list):
            return [str(t) for t in topics[:max_topics]]
    except json.JSONDecodeError:
        pass

    # Fallback: split by newlines or commas
    topics = [t.strip() for t in content.replace("[", "").replace("]", "").split("\n")]
    topics = [t for t in topics if t]
    return topics[:max_topics]
