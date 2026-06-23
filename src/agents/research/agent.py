"""Research Agent — citation graph + knowledge graph discovery and synthesis.

Implements the 8-step pipeline:
1. REUSE: get_existing_research
2. SEED: Semantic Scholar search + arXiv supplementary
3. EXPAND: follow references + citations (BFS, novelty-gated)
4. ENRICH: LLM-synthesize conclusion + notes per new paper
5. EXTRACT: entity extraction + relation extraction → concept graph
6. LINK: papers↔concepts, interest↔papers, interest↔concepts
7. PERSIST: idempotent upserts + research_run record
8. SUMMARIZE: LLM "what's new" paragraph
"""

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from typing import Any, Literal, Optional

from src.agents.research.skills.entity_extraction import extract_entities
from src.agents.research.skills.paper_synthesis import synthesize_paper
from src.agents.research.skills.relation_extraction import extract_relations
from src.agents.research.skills.summarization import summarize_run
from src.agents.research.tools.arxiv_connector import ArxivConnector
from src.agents.research.tools.openalex_connector import OpenAlexConnector
from src.agents.research.tools.semantic_scholar import SemanticScholarConnector
from src.store.knowledge import UnifiedKnowledgeStore, compute_citation_id

logger = logging.getLogger(__name__)


@dataclass
class ResearchResult:
    """Result of a research run."""

    topic: str
    new_papers: int
    new_concepts: int
    new_edges: int
    summary: str
    run_id: Optional[str] = None


class ResearchAgent:
    """Citation graph + knowledge graph research agent."""

    def __init__(
        self,
        llm: Any,
        store: UnifiedKnowledgeStore,
        config: Optional[dict[str, Any]] = None,
    ):
        self.llm = llm
        self.store = store
        self.config = config or {}

        # Connectors (OpenAlex is fallback when Semantic Scholar is rate-limited)
        self.semantic_scholar = SemanticScholarConnector(self.config)
        self.openalex = OpenAlexConnector(self.config)
        self.arxiv = ArxivConnector(self.config)

        # Config with sensible defaults
        self.semantic_scholar_max_results = self.config.get("semantic_scholar_max_results", 20)
        self.arxiv_max_results = self.config.get("arxiv_max_results", 10)
        self.max_citation_depth = self.config.get("max_citation_depth", 2)
        self.min_entity_confidence = self.config.get("min_entity_confidence", 0.6)
        self.entity_extraction_max = self.config.get("entity_extraction_max", 20)

    async def research(
        self,
        topic: str,
        *,
        interest_id: Optional[str] = None,
        depth: Optional[Literal["shallow", "normal", "deep"]] = None,
        trigger_source: str = "manual",
        publish: Optional[Any] = None,
        job_id: Optional[str] = None,
    ) -> ResearchResult:
        """Execute the 8-step research pipeline.

        Args:
            topic: Research topic
            interest_id: Link to interest (for G6 graph linking)
            depth: Override depth decision (shallow/normal/deep)
            trigger_source: Origin ("manual", "interest_trigger", etc.)
            publish: EventBus for publishing Progress events (Path B)
            job_id: Job ID for event publishing

        Returns:
            ResearchResult with counts and summary
        """
        logger.info("=" * 70)
        logger.info(f"🔍 RESEARCH AGENT: Starting research on '{topic}'")
        logger.info(f"   Trigger: {trigger_source} | Interest: {interest_id or 'none'}")
        logger.info("=" * 70)

        run_id = await self.store.start_research_run(
            {
                "topic": topic,
                "interest_id": interest_id,
                "trigger_source": trigger_source,
            }
        )

        try:
            # Step 1: REUSE — get existing research
            logger.info("[1/8] REUSE: Checking for existing research...")
            existing = await self.store.get_existing_research(topic, interest_id=interest_id)
            existing_papers = set(existing.keys()) if existing else set()
            logger.info(
                f"      Found {len(existing_papers)} existing papers "
                f"({', '.join(list(existing_papers)[:3])}{'...' if len(existing_papers) > 3 else ''})"
            )

            # Step 2: SEED — decide depth and search
            if depth is None:
                depth = self._decide_depth(
                    topic,
                    len(existing_papers),
                    trigger_strength=0.5,  # Default; would come from Interest Agent in production
                )

            logger.info(f"[2/8] SEED: Searching sources (depth={depth})...")
            sources = self._prioritize_sources(topic, depth)
            logger.info(f"      Sources: {', '.join(sources)}")
            papers_by_id = {}

            for source in sources:
                if source == "semantic_scholar":
                    # Try Semantic Scholar first
                    logger.info(f"      → Semantic Scholar (limit={self.semantic_scholar_max_results})...")
                    raw_papers = await self.semantic_scholar.search(
                        topic, limit=self.semantic_scholar_max_results
                    )
                    # If empty/failed, fallback to OpenAlex (free, no rate limits)
                    if not raw_papers:
                        logger.info("        ⚠️  Semantic Scholar returned no results, falling back to OpenAlex")
                        raw_papers = await self.openalex.search(
                            topic, limit=self.semantic_scholar_max_results
                        )
                        logger.info(f"        ✓ OpenAlex returned {len(raw_papers)} papers")
                    else:
                        logger.info(f"        ✓ Found {len(raw_papers)} papers")
                elif source == "arxiv":
                    logger.info(f"      → arXiv (limit={self.arxiv_max_results})...")
                    raw_papers = await self.arxiv.search(
                        topic, limit=self.arxiv_max_results
                    )
                    logger.info(f"        ✓ Found {len(raw_papers)} papers")
                else:
                    raw_papers = []

                for raw_paper in raw_papers:
                    citation_dict = raw_paper.to_citation_dict()
                    citation_id = await self.store.upsert_citation(citation_dict)
                    papers_by_id[citation_id] = (raw_paper, citation_dict)

            logger.info(f"      Total seed papers: {len(papers_by_id)}")

            # Step 3: EXPAND — citation frontier (BFS, novelty-gated)
            logger.info(f"[3/8] EXPAND: Following citation frontier (max_depth={self.max_citation_depth})...")
            frontier_papers = {}
            if depth in ("normal", "deep"):
                frontier_papers = await self._expand_citations(
                    papers_by_id,
                    max_depth=self.max_citation_depth if depth == "deep" else 1,
                    existing=existing_papers,
                )
                logger.info(f"      Found {len(frontier_papers)} papers in citation frontier")
                papers_by_id.update(frontier_papers)
            else:
                logger.info("      Skipping (shallow depth)")

            # Step 4: ENRICH — LLM synthesis per new paper
            new_papers = [cid for cid in papers_by_id.keys() if cid not in existing_papers]
            logger.info(f"[4/8] ENRICH: Synthesizing conclusions for {len(new_papers)} new papers...")

            for i, citation_id in enumerate(new_papers, 1):
                raw_paper, citation_dict = papers_by_id[citation_id]
                logger.debug(f"      [{i}/{len(new_papers)}] {raw_paper.title[:60]}...")
                synthesis = await synthesize_paper(
                    title=raw_paper.title,
                    abstract=raw_paper.abstract or "",
                    tldr=raw_paper.tldr or "",
                    llm=self.llm,
                    source_id=citation_id,
                )
                await self.store.update_citation_notes(
                    citation_id,
                    conclusion=synthesis.conclusion,
                    notes=synthesis.notes,
                )
            logger.info(f"      ✓ Synthesis complete")

            # Step 5: EXTRACT — entity + relation extraction → concept graph
            logger.info(f"[5/8] EXTRACT: Mining concepts and relationships...")
            concepts_by_name = {}
            concept_edge_count = 0

            for i, citation_id in enumerate(new_papers, 1):
                raw_paper, _ = papers_by_id[citation_id]
                if not raw_paper.abstract:
                    continue

                logger.debug(
                    f"      [{i}/{len(new_papers)}] Extracting from: {raw_paper.title[:50]}..."
                )

                # Entity extraction
                entity_result = await extract_entities(
                    raw_paper.abstract,
                    self.llm,
                    citation_id,
                    max_entities=self.entity_extraction_max,
                    min_confidence=self.min_entity_confidence,
                )

                concept_ids = {}
                for entity in entity_result.entities:
                    concept_dict = {
                        "label": entity.name,
                        "category": entity.category,
                        "description": entity.description,
                        "source": "research",
                    }
                    concept_id = await self.store.upsert_concept(concept_dict)
                    concept_ids[entity.name] = (concept_id, entity.category)
                    concepts_by_name[entity.name] = (concept_id, entity.category, concept_dict)

                logger.debug(f"        • Extracted {len(entity_result.entities)} concepts")

                # Relation extraction
                if len(concept_ids) >= 2:
                    concept_names = list(concept_ids.keys())
                    relation_result = await extract_relations(
                        concept_names,
                        self.llm,
                        citation_id,
                    )

                    for relation in relation_result.relations:
                        source_id = concept_ids.get(relation.source, (None, None))[0]
                        target_id = concept_ids.get(relation.target, (None, None))[0]

                        if source_id and target_id:
                            await self.store.add_concept_relationship(
                                source_id,
                                target_id,
                                relation.relation_type,
                                weight=relation.weight,
                                evidence=relation.evidence,
                            )
                            concept_edge_count += 1

                    logger.debug(
                        f"        • Extracted {len(relation_result.relations)} relationships"
                    )

            logger.info(
                f"      ✓ Total concepts: {len(concepts_by_name)} | "
                f"Relationships: {concept_edge_count}"
            )

            # Step 6: LINK — papers↔concepts, interest↔papers, interest↔concepts
            logger.info(f"[6/8] LINK: Connecting papers, concepts, and interests...")
            interest_links = 0
            concept_links = 0

            for citation_id in new_papers:
                raw_paper, _ = papers_by_id[citation_id]

                # Link interest to citation (if interest_id provided)
                if interest_id:
                    await self.store.link_interest_to_citation(interest_id, citation_id)
                    interest_links += 1

                # Link concepts to this paper and interest
                if raw_paper.abstract:
                    entity_result = await extract_entities(
                        raw_paper.abstract,
                        self.llm,
                        citation_id,
                        max_entities=self.entity_extraction_max,
                        min_confidence=self.min_entity_confidence,
                    )

                    for entity in entity_result.entities:
                        concept_id = concepts_by_name.get(entity.name, (None, None, None))[0]
                        if concept_id:
                            # Citation ↔ Concept
                            await self.store.link_citation_to_concept(citation_id, concept_id)
                            concept_links += 1

                            # Interest ↔ Concept (if interest_id provided)
                            if interest_id:
                                await self.store.link_interest_to_concept(interest_id, concept_id)

            logger.info(
                f"      ✓ Interest links: {interest_links} | Concept links: {concept_links}"
            )

            # Step 7 & 8: PERSIST — record run deltas & SUMMARIZE
            logger.info(f"[7/8] PERSIST: Recording research run...")
            summary_text = ""
            if new_papers:
                logger.info(f"[8/8] SUMMARIZE: Generating summary...")
                summary_obj = await summarize_run(
                    topic,
                    [papers_by_id[cid][1] for cid in new_papers],
                    [
                        {"name": name, "category": cat}
                        for name, (_, cat, _) in concepts_by_name.items()
                    ],
                    self.llm,
                )
                summary_text = summary_obj
                logger.info(f"      Summary ({len(summary_text)} chars): {summary_text[:80]}...")
            else:
                logger.info("[8/8] SUMMARIZE: (no new papers)")

            await self.store.finish_research_run(
                run_id,
                status="completed",
                summary=summary_text,
                papers_new=len(new_papers),
                concepts_new=len(concepts_by_name),
            )

            logger.info("=" * 70)
            logger.info(f"✅ RESEARCH COMPLETE")
            logger.info(
                f"   New papers: {len(new_papers)} | New concepts: {len(concepts_by_name)} | "
                f"Edges: {concept_edge_count}"
            )
            logger.info("=" * 70)

            return ResearchResult(
                topic=topic,
                new_papers=len(new_papers),
                new_concepts=len(concepts_by_name),
                new_edges=concept_edge_count,
                summary=summary_text,
                run_id=run_id,
            )

        except Exception as e:
            logger.error("=" * 70)
            logger.error(f"❌ RESEARCH FAILED: {e}")
            logger.error("=" * 70)
            raise

    def _decide_depth(
        self,
        topic: str,
        existing_count: int,
        trigger_strength: float = 0.5,
    ) -> Literal["shallow", "normal", "deep"]:
        """Decide research depth based on interest strength and existing research.

        - Strong new interest (strength > 0.7, little existing) → deep
        - Moderate interest or some existing research → normal
        - Weak reinforcement or lots of existing → shallow
        """
        if trigger_strength > 0.7 and existing_count < 3:
            return "deep"
        if existing_count > 10:
            return "shallow"
        return "normal"

    def _prioritize_sources(
        self, topic: str, depth: Literal["shallow", "normal", "deep"]
    ) -> list[str]:
        """Decide which connectors to use in order of preference.

        Theory/science topics weight Semantic Scholar + arXiv.
        Applied/tool topics weight Semantic Scholar.
        """
        theory_keywords = ["model", "architecture", "theory", "algorithm", "framework", "neural"]
        is_theoretical = any(kw in topic.lower() for kw in theory_keywords)

        if depth == "deep":
            return ["semantic_scholar", "arxiv"] if is_theoretical else ["semantic_scholar"]
        elif depth == "normal":
            return ["semantic_scholar", "arxiv"] if is_theoretical else ["semantic_scholar"]
        else:  # shallow
            return ["semantic_scholar"]

    async def _expand_citations(
        self,
        seed_papers: dict[str, tuple],
        max_depth: int,
        existing: set[str],
    ) -> dict[str, tuple]:
        """BFS citation expansion: follow references and citations (G2).

        Yields new papers until max_depth or novelty threshold drops.
        """
        frontier = {}
        visited = set(seed_papers.keys())
        queue = deque((cid, 0) for cid in seed_papers.keys())
        ref_counts = {cid: 0 for cid in seed_papers.keys()}

        while queue:
            citation_id, depth = queue.popleft()

            if depth >= max_depth:
                continue

            raw_paper = seed_papers.get(citation_id, (None, None))[0]
            if not raw_paper or not raw_paper.semantic_scholar_id:
                continue

            # Fetch references and citations in parallel
            refs_task = self.semantic_scholar.get_references(
                raw_paper.semantic_scholar_id, limit=10
            )
            cites_task = self.semantic_scholar.get_citations(
                raw_paper.semantic_scholar_id, limit=10
            )
            refs, cites = await asyncio.gather(refs_task, cites_task, return_exceptions=True)

            if isinstance(refs, Exception):
                refs = []
            if isinstance(cites, Exception):
                cites = []

            for neighbor_paper in refs + cites:
                neighbor_dict = neighbor_paper.to_citation_dict()
                neighbor_id = compute_citation_id(neighbor_dict)

                if neighbor_id not in visited and neighbor_id not in existing:
                    # Check if still worth chasing (diminishing novelty)
                    if self._worth_chasing(neighbor_paper, len(frontier), depth):
                        visited.add(neighbor_id)
                        frontier[neighbor_id] = (neighbor_paper, neighbor_dict)
                        queue.append((neighbor_id, depth + 1))
                        ref_counts[neighbor_id] = ref_counts.get(citation_id, 0) + 1

                elif neighbor_id not in visited:
                    visited.add(neighbor_id)
                    # Add edge even if not novel (for graph connectivity)
                    await self.store.add_citation_edge(citation_id, neighbor_id, "references")

        return frontier

    def _worth_chasing(self, paper: Any, frontier_size: int, hops: int) -> bool:
        """Novelty gate: stop expanding if diminishing returns.

        Papers with high citation counts or recent publication are more likely to be worth chasing.
        """
        # Simple heuristic: stop if frontier is large and we're deep
        if frontier_size > 100 and hops > 1:
            return False

        # Favor highly-cited papers
        if hasattr(paper, "citation_count") and paper.citation_count < 1:
            return False

        return True
