"""Flat tool registry for the Brainstorming Agent's 9 capabilities.

Mirrors the reference repo's flat tools.py + get_available_tools() convention.
Tools are rebuilt fresh per turn via get_available_tools(deps) because
user_id/thread_id/turn bookkeeping are request-scoped while store/llm are
long-lived singletons -- rebuilding a handful of closures per turn is cheap
and keeps the compiled StateGraph itself user/thread-agnostic.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ...store.knowledge import UnifiedKnowledgeStore, compute_concept_id

logger = logging.getLogger(__name__)

# Strength policy for register_interest, per source of the signal.
INTEREST_STRENGTH_BY_SOURCE = {
    "explicit": 0.85,
    "conversation": 0.55,
    "web_search": 0.50,
}

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


@dataclass
class TurnContext:
    """Per-turn side-channel bookkeeping, mutated directly by tool closures.

    Kept outside the checkpointed LangGraph state so tools can append to it
    without LangGraph's Command/state-update machinery.
    """

    gathered_sources: list[dict[str, Any]] = field(default_factory=list)
    registered_interests: list[str] = field(default_factory=list)
    registered_knowledge: list[str] = field(default_factory=list)


@dataclass
class ToolDeps:
    """Dependencies a turn's tools are bound to."""

    store: UnifiedKnowledgeStore
    llm: Any  # OpenRouterRuntime - used for synthesis-only skills, no tool-calling needed
    user_id: str
    thread_id: str
    turn: TurnContext
    tavily_api_key: Optional[str] = None


def get_available_tools(deps: ToolDeps) -> list[StructuredTool]:
    """Build the 9 capability tools bound to this turn's dependencies."""
    return [
        _build_web_search(deps),
        _build_search_knowledge_base(deps),
        _build_register_interest(deps),
        _build_show_research_graph(deps),
        _build_register_knowledge(deps),
        _build_deep_research(deps),
        _build_research_documentation(deps),
        _build_research_gap_analysis(deps),
        _build_solution_proposal(deps),
    ]


# ========== 1. web_search ==========


class WebSearchArgs(BaseModel):
    query: str = Field(description="Search query")
    max_results: int = Field(default=5, description="Max number of results to return (1-10)")


def _build_web_search(deps: ToolDeps) -> StructuredTool:
    async def _run(query: str, max_results: int = 5) -> str:
        logger.info(f"[Tool] Calling web_search with query: '{query}'")
        if not deps.tavily_api_key:
            return "Web search is unavailable: no TAVILY_API_KEY configured."

        max_results = max(1, min(max_results, 10))
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    TAVILY_SEARCH_URL,
                    json={
                        "api_key": deps.tavily_api_key,
                        "query": query,
                        "max_results": max_results,
                        "search_depth": "basic",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            logger.warning(f"Tavily search failed for '{query}': {e}")
            return f"Web search failed: {e}"

        results = data.get("results", [])
        if not results:
            return f"No web results found for '{query}'."

        lines = []
        for r in results:
            entry = {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": (r.get("content") or "")[:500],
            }
            deps.turn.gathered_sources.append(entry)
            lines.append(f"- {entry['title']} ({entry['url']}): {entry['snippet']}")

        return "\n".join(lines)

    return StructuredTool.from_function(
        coroutine=_run,
        name="web_search",
        description=(
            "Search the web for current information on a topic. "
            "Returns titled results with URLs and snippets."
        ),
        args_schema=WebSearchArgs,
    )


# ========== 2. search_knowledge_base ==========


class SearchKBArgs(BaseModel):
    query: str = Field(description="What to search for in the knowledge base")
    limit: int = Field(default=5, description="Max number of results")


def _build_search_knowledge_base(deps: ToolDeps) -> StructuredTool:
    async def _run(query: str, limit: int = 5) -> str:
        logger.info(f"[Tool] Calling search_knowledge_base with query: '{query}'")
        entries = await deps.store.search_knowledge_entries(query, limit=limit)
        concepts = await deps.store.find_concepts_by_label(query)

        if not entries and not concepts:
            return f"No knowledge base entries found for '{query}'."

        lines = []
        for e in entries:
            lines.append(f"[Q&A] Q: {e['question']}\n      A: {(e['answer'] or '')[:300]}")
        for c in concepts:
            lines.append(
                f"[Concept] {c['label']} ({c.get('category', 'general')}): "
                f"{c.get('description') or 'no description'}"
            )

        return "\n".join(lines)

    return StructuredTool.from_function(
        coroutine=_run,
        name="search_knowledge_base",
        description=(
            "Search the user's existing knowledge base (past Q&A and stored "
            "concepts) for relevant information already known, before researching anew."
        ),
        args_schema=SearchKBArgs,
    )


# ========== 3. register_interest ==========


class RegisterInterestArgs(BaseModel):
    topic: str = Field(description="The topic/interest label to register, e.g. 'rust async runtimes'")
    source: str = Field(
        default="conversation",
        description=(
            "Where this interest signal came from: 'explicit' (user directly said "
            "they're interested), 'conversation' (inferred from discussion), or "
            "'web_search' (surfaced while researching)."
        ),
    )


def _build_register_interest(deps: ToolDeps) -> StructuredTool:
    async def _run(topic: str, source: str = "conversation") -> str:
        logger.info(f"[Tool] Calling register_interest with topic: '{topic}' (source={source})")
        topic = topic.strip().lower()
        if not topic:
            return "Cannot register an empty interest topic."

        confidence = INTEREST_STRENGTH_BY_SOURCE.get(source, INTEREST_STRENGTH_BY_SOURCE["conversation"])
        signal_id = f"brainstorm:{deps.thread_id}:{uuid.uuid4().hex[:8]}"

        await deps.store.add_classified_signal(
            signal_id=signal_id,
            topic=topic,
            confidence=confidence,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        deps.turn.registered_interests.append(topic)
        strength = await deps.store.get_strength(topic)
        return f"Registered interest '{topic}' (source={source}, current strength={strength:.2f})."

    return StructuredTool.from_function(
        coroutine=_run,
        name="register_interest",
        description=(
            "Record that the user has shown interest in a topic so it feeds the "
            "interest model. Call this when the user expresses genuine interest, "
            "not for every passing mention."
        ),
        args_schema=RegisterInterestArgs,
    )


async def register_interest_directly(deps: ToolDeps, topic: str, source: str = "conversation") -> str:
    """Register an interest without going through the LLM tool-calling loop.

    Used by the end-of-turn auto-extraction node, which detects interests
    implied by the conversation rather than ones the model explicitly called
    the register_interest tool for.
    """
    tool = _build_register_interest(deps)
    return await tool.ainvoke({"topic": topic, "source": source})


# ========== 4. show_research_graph ==========


class ShowGraphArgs(BaseModel):
    topic: Optional[str] = Field(
        default=None,
        description="Topic/interest label to center the graph on. Omit to use the user's top interests.",
    )
    max_depth: int = Field(default=2, description="How many relationship hops to traverse")


def _build_show_research_graph(deps: ToolDeps) -> StructuredTool:
    async def _run(topic: Optional[str] = None, max_depth: int = 2) -> str:
        logger.info(f"[Tool] Calling show_research_graph (topic={topic}, depth={max_depth})")
        interests: Optional[list[str]]
        if topic:
            interests = [topic]
        else:
            top = await deps.store.get_interests(min_strength=0.3)
            interests = [i["label"] for i in top[:5]]
            if not interests:
                return "No interests with enough strength yet to build a research graph."

        nodes, edges = await deps.store.relevant_subgraphs(interests=interests, max_depth=max_depth)
        if not nodes:
            return f"No concept graph found yet for: {', '.join(interests)}."

        node_lines = [f"- {n['label']} ({n.get('category', 'general')})" for n in nodes]
        edge_lines = [
            f"- {e['source_id']} --{e['relation_type']}--> {e['target_id']}" for e in edges
        ]
        return (
            f"Concepts ({len(nodes)}):\n"
            + "\n".join(node_lines)
            + f"\n\nRelationships ({len(edges)}):\n"
            + ("\n".join(edge_lines) if edge_lines else "(none)")
        )

    return StructuredTool.from_function(
        coroutine=_run,
        name="show_research_graph",
        description=(
            "Show the concept/citation knowledge graph around a topic (or the "
            "user's top interests if no topic is given)."
        ),
        args_schema=ShowGraphArgs,
    )


# ========== 5. register_knowledge ==========


class RegisterKnowledgeArgs(BaseModel):
    title: str = Field(description="Short title for this piece of knowledge/source")
    summary: str = Field(description="Summary of what was learned")
    source_url: str = Field(default="", description="URL of the source, if any")
    concepts: list[str] = Field(
        default_factory=list, description="Key concept labels extracted from this knowledge"
    )


def _build_register_knowledge(deps: ToolDeps) -> StructuredTool:
    async def _run(
        title: str, summary: str, source_url: str = "", concepts: Optional[list[str]] = None
    ) -> str:
        logger.info(f"[Tool] Calling register_knowledge with title: '{title}' (concepts={len(concepts or [])})")
        concepts = concepts or []
        citation_id = compute_concept_id(title, category="citation")
        abstract = f"{summary}\n\nSource: {source_url}" if source_url else summary
        await deps.store.upsert_citation({"id": citation_id, "title": title, "abstract": abstract})

        concept_ids = []
        for label in concepts:
            cid = compute_concept_id(label, category="general")
            await deps.store.upsert_concept({"id": cid, "label": label, "category": "general"})
            await deps.store.link_citation_to_concept(citation_id, cid)
            concept_ids.append(cid)

        for source_id, target_id in zip(concept_ids, concept_ids[1:]):
            await deps.store.add_concept_relationship(source_id, target_id, "co_occurs_with", weight=0.6)

        deps.turn.registered_knowledge.append(title)
        return f"Registered knowledge '{title}' with {len(concept_ids)} linked concept(s)."

    return StructuredTool.from_function(
        coroutine=_run,
        name="register_knowledge",
        description=(
            "Persist a piece of researched knowledge (a source/finding) into the "
            "knowledge graph, linking it to key concepts."
        ),
        args_schema=RegisterKnowledgeArgs,
    )


# ========== 6. deep_research ==========


_DEPTH_TO_RESULTS = {"shallow": 3, "normal": 5, "deep": 8}


class DeepResearchArgs(BaseModel):
    topic: str = Field(description="Topic to research deeply")
    depth: str = Field(
        default="normal", description="'shallow', 'normal', or 'deep' -- controls how many sources to gather"
    )


def _build_deep_research(deps: ToolDeps) -> StructuredTool:
    async def _run(topic: str, depth: str = "normal") -> str:
        logger.info(f"[Tool] Calling deep_research with topic: '{topic}' (depth={depth})")
        max_results = _DEPTH_TO_RESULTS.get(depth, 5)

        sources_text = "Web search not configured."
        if deps.tavily_api_key:
            web_tool = _build_web_search(deps)
            sources_text = await web_tool.ainvoke({"query": topic, "max_results": max_results})

        kb_tool = _build_search_knowledge_base(deps)
        kb_text = await kb_tool.ainvoke({"query": topic, "limit": 5})

        prompt = f"""Synthesize a deep research summary on: {topic}

Web sources:
{sources_text}

Existing knowledge base:
{kb_text}

Write a structured summary covering: key facts, important sub-topics, and open
questions. Be concise but substantive."""

        response = await deps.llm.chat(messages=[{"role": "user", "content": prompt}], model_role="meta")
        summary = response.content

        register_tool = _build_register_knowledge(deps)
        await register_tool.ainvoke(
            {"title": f"Deep research: {topic}", "summary": summary, "concepts": [topic]}
        )

        return summary

    return StructuredTool.from_function(
        coroutine=_run,
        name="deep_research",
        description=(
            "Perform deep research on a topic: gathers web sources and existing "
            "knowledge, synthesizes a structured summary, and persists it to the "
            "knowledge graph."
        ),
        args_schema=DeepResearchArgs,
    )


# ========== 7. research_documentation ==========


class ResearchDocsArgs(BaseModel):
    topic: str = Field(description="Topic or technology to produce documentation-style notes for")


def _build_research_documentation(deps: ToolDeps) -> StructuredTool:
    async def _run(topic: str) -> str:
        logger.info(f"[Tool] Calling research_documentation with topic: '{topic}'")
        prompt = f"""Write concise reference documentation notes for: {topic}

Cover: what it is, core concepts/API surface, common usage patterns, and
gotchas. Format as markdown with headers."""
        response = await deps.llm.chat(messages=[{"role": "user", "content": prompt}], model_role="meta")
        return response.content

    return StructuredTool.from_function(
        coroutine=_run,
        name="research_documentation",
        description="Produce structured reference documentation/notes on a topic or technology.",
        args_schema=ResearchDocsArgs,
    )


# ========== 8. research_gap_analysis ==========


class GapAnalysisArgs(BaseModel):
    topic: str = Field(description="Topic or domain to analyze")
    current_approach: str = Field(
        default="", description="The user's current approach or solution, if any, to compare against"
    )


def _build_research_gap_analysis(deps: ToolDeps) -> StructuredTool:
    async def _run(topic: str, current_approach: str = "") -> str:
        logger.info(f"[Tool] Calling research_gap_analysis with topic: '{topic}'")
        context = f"\n\nCurrent approach to compare against:\n{current_approach}" if current_approach else ""
        prompt = f"""Perform a gap analysis on: {topic}{context}

Identify: what's missing, weaknesses, unexplored angles, and risks. Be
specific and actionable."""
        response = await deps.llm.chat(messages=[{"role": "user", "content": prompt}], model_role="meta")
        return response.content

    return StructuredTool.from_function(
        coroutine=_run,
        name="research_gap_analysis",
        description="Analyze gaps, weaknesses, or unexplored angles in a topic or in the user's current approach.",
        args_schema=GapAnalysisArgs,
    )


# ========== 9. solution_proposal ==========


class SolutionProposalArgs(BaseModel):
    problem: str = Field(description="The problem to solve")
    constraints: str = Field(default="", description="Known constraints (tech stack, time, budget, etc.)")


def _build_solution_proposal(deps: ToolDeps) -> StructuredTool:
    async def _run(problem: str, constraints: str = "") -> str:
        logger.info(f"[Tool] Calling solution_proposal for problem: '{problem[:50]}...'")
        context = f"\n\nConstraints:\n{constraints}" if constraints else ""
        prompt = f"""Propose 2-3 concrete solutions for this problem: {problem}{context}

For each: brief description, tradeoffs, and a recommendation of which to pick
and why."""
        response = await deps.llm.chat(messages=[{"role": "user", "content": prompt}], model_role="meta")
        return response.content

    return StructuredTool.from_function(
        coroutine=_run,
        name="solution_proposal",
        description="Propose concrete solution options for a stated problem, with tradeoffs and a recommendation.",
        args_schema=SolutionProposalArgs,
    )
