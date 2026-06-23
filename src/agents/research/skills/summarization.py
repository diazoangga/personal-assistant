"""Summarization skill — one-paragraph summary of a research run's discoveries.

Takes new papers and concepts from a run, generates a cited "what's new" paragraph
for storage in `research_runs.summary`.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def summarize_run(
    topic: str,
    new_papers: list[dict[str, Any]],
    new_concepts: list[dict[str, Any]],
    llm: Any,
) -> str:
    """Summarize the discoveries from a research run.

    Args:
        topic: The research topic
        new_papers: List of newly-discovered papers (min fields: title, authors, year)
        new_concepts: List of newly-extracted concepts (min fields: name, category)
        llm: LLM runtime with chat() method

    Returns:
        One-paragraph summary as a string
    """
    if not new_papers and not new_concepts:
        return ""

    # Build paper list for context
    paper_refs = []
    for p in new_papers[:5]:  # Top 5 to keep context bounded
        title = p.get("title", "Unknown")
        year = p.get("year")
        authors = p.get("authors")
        if isinstance(authors, str):
            try:
                authors = json.loads(authors)
            except (json.JSONDecodeError, TypeError):
                authors = []
        author_str = authors[0] if authors else "Unknown"
        year_str = f" ({year})" if year else ""
        paper_refs.append(f"- {title} by {author_str}{year_str}")

    concept_names = [c.get("name", "") for c in new_concepts[:10]]
    concept_str = ", ".join(c for c in concept_names if c)

    prompt = f"""Summarize the key discoveries from research on "{topic}".

New papers found:
{chr(10).join(paper_refs) if paper_refs else "(none)"}

New concepts identified:
{concept_str if concept_str else "(none)"}

Write ONE paragraph (2-3 sentences) summarizing what was discovered. Be concise and specific.
Mention the most significant papers or concepts. Reference the papers by author/year.

Summary paragraph:"""

    response = await llm.chat(
        messages=[{"role": "user", "content": prompt}],
        model_role="meta",
    )

    summary = (response.content or "").strip()
    if summary.startswith("```"):
        parts = summary.split("```")
        summary = parts[1] if len(parts) > 1 else summary
        summary = summary.strip()

    return summary[:500]  # Cap at 500 chars
