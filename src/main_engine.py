"""Engine wrapper - integrates all components for CLI usage."""

import asyncio
import logging
from typing import Any, Optional

from .core.engine import Engine
from .core.bus import EventBus
from .store.vector import KnowledgeBase
from .store.memory import UserMemory
from .store.graph import CitationGraph, KnowledgeGraph
from .ingest.pipeline import IngestPipeline
from .llm.openrouter import OpenRouterRuntime

logger = logging.getLogger(__name__)


class PersonalAssistantEngine:
    """
    High-level engine wrapper that integrates all components.

    Usage:
        engine = PersonalAssistantEngine(config)
        await engine.initialize()
        job_id = await engine.ask("What is ML?")
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._engine: Optional[Engine] = None
        self._llm: Optional[OpenRouterRuntime] = None
        self._kb: Optional[KnowledgeBase] = None
        self._memory: Optional[UserMemory] = None
        self._citation_graph: Optional[CitationGraph] = None
        self._knowledge_graph: Optional[KnowledgeGraph] = None
        self._ingest: Optional[IngestPipeline] = None

    async def initialize(self) -> None:
        """Initialize all components."""
        logger.info("Initializing PersonalAssistantEngine...")
        
        # Initialize LLM
        logger.debug("Initializing LLM runtime...")
        self._llm = OpenRouterRuntime(config=self.config)
        
        # Initialize storage
        logger.debug("Initializing knowledge base...")
        self._kb = KnowledgeBase(config=self.config, llm=self._llm)
        await self._kb.initialize()
        
        # Initialize memory
        memory_db = self.config.get("memory_db", "./data/memory.db")
        logger.debug(f"Initializing user memory (db={memory_db})...")
        self._memory = UserMemory(memory_db)
        await self._memory.initialize()
        
        # Initialize graphs
        citation_db = self.config.get("citation_graph_db", "./data/citations.db")
        logger.debug(f"Initializing citation graph (db={citation_db})...")
        self._citation_graph = CitationGraph(citation_db)
        await self._citation_graph.initialize()
        
        knowledge_db = self.config.get("knowledge_graph_db", "./data/concepts.db")
        logger.debug(f"Initializing knowledge graph (db={knowledge_db})...")
        self._knowledge_graph = KnowledgeGraph(knowledge_db)
        await self._knowledge_graph.initialize()
        
        # Initialize ingest pipeline
        logger.debug("Initializing ingest pipeline...")
        self._ingest = IngestPipeline(self.config)
        
        # Create core engine (with stub agents for now)
        logger.debug("Creating core engine...")
        self._engine = Engine(
            llm=self._llm,
            store=self._kb,
            memory=self._memory,
            graph=self._knowledge_graph,
            ingest=self._ingest,
        )
        
        logger.info("PersonalAssistantEngine initialized successfully")

    async def shutdown(self) -> None:
        """Clean shutdown of all components."""
        logger.info("Shutting down PersonalAssistantEngine...")
        
        if self._memory:
            logger.debug("Closing user memory...")
            await self._memory.close()
        if self._citation_graph:
            logger.debug("Closing citation graph...")
            await self._citation_graph.close()
        if self._knowledge_graph:
            logger.debug("Closing knowledge graph...")
            await self._knowledge_graph.close()
            
        logger.info("PersonalAssistantEngine shutdown complete")

    @property
    def bus(self) -> EventBus:
        """Get the event bus for streaming."""
        assert self._engine is not None
        return self._engine._bus

    async def ask(self, query: str, user: str = "cli") -> str:
        """Ask a question and return the answer."""
        from .core.commands import Ask
        
        assert self._engine is not None
        logger.info(f"Processing query: {query[:50]}...")
        
        # For now, use LLM directly since agents aren't implemented
        if not self._llm:
            raise RuntimeError("LLM not initialized")
        
        response = await self._llm.chat(
            messages=[{"role": "user", "content": query}],
            model_role="meta",
        )
        logger.debug(f"Query answered ({len(response.content)} chars)")
        return response.content

    async def brainstorm(self, topic: str, user: str = "cli") -> str:
        """Start a brainstorming session."""
        from .core.commands import Brainstorm
        
        assert self._engine is not None
        logger.info(f"Brainstorming topic: {topic}")
        
        if not self._llm:
            raise RuntimeError("LLM not initialized")
        
        prompt = f"Let's brainstorm about {topic}. What are some interesting angles, ideas, or considerations?"
        response = await self._llm.chat(
            messages=[{"role": "user", "content": prompt}],
            model_role="meta",
        )
        logger.debug(f"Brainstorming completed ({len(response.content)} chars)")
        return response.content

    async def research(self, topic: str, depth: int = 2, user: str = "cli") -> str:
        """Research a topic."""
        from .core.commands import ResearchTopic
        
        assert self._engine is not None
        logger.info(f"Researching topic: {topic} (depth={depth})")
        
        if not self._llm:
            raise RuntimeError("LLM not initialized")
        
        prompt = f"Provide a comprehensive research overview of: {topic}. Include key concepts, recent developments, and important papers or resources."
        response = await self._llm.chat(
            messages=[{"role": "user", "content": prompt}],
            model_role="meta",
        )
        logger.debug(f"Research completed ({len(response.content)} chars)")
        return response.content

    async def ingest_github(self, user_github: str | None = None) -> dict[str, Any]:
        """Fetch GitHub activity."""
        assert self._ingest is not None
        logger.info("Starting GitHub ingestion...")
        
        results = await self._ingest.run("github")
        if not results:
            logger.warning("GitHub ingestion returned no results")
            return {"error": "No results"}
        
        result = results[0]
        logger.debug(f"Fetched {len(result.signals)} signals from GitHub")
        
        stats = await self._ingest.process_signals(result.signals)
        logger.info(f"GitHub ingestion complete: {stats}")
        
        # Store activities in memory
        if self._memory and result.signals:
            for signal in result.signals[:10]:  # Limit for now
                # Could classify and update interests here
                pass
        
        return stats

    async def get_interests(self, min_strength: float = 0.0) -> list[dict[str, Any]]:
        """Get user's current interests."""
        assert self._memory is not None
        logger.debug(f"Fetching interests (min_strength={min_strength})")
        
        nodes = await self._memory.get_interests(min_strength=min_strength)
        logger.debug(f"Found {len(nodes)} interests")
        return [node.to_dict() for node in nodes]

    async def add_interest(self, label: str, strength: float = 0.5) -> None:
        """Manually add an interest."""
        from .store.memory import InterestNode
        from datetime import datetime
        
        assert self._memory is not None
        logger.info(f"Adding interest: {label} (strength={strength})")
        
        node = InterestNode(
            id=label.lower().replace(" ", "-"),
            label=label,
            strength=strength,
            last_active=datetime.utcnow().isoformat(),
        )
        await self._memory.upsert_interest(node)
        logger.debug(f"Interest '{label}' added successfully")


# Factory function
def create_engine(config: dict[str, Any]) -> PersonalAssistantEngine:
    """Create and initialize a PA engine."""
    return PersonalAssistantEngine(config)
