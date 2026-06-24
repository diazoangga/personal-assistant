"""Engine wrapper - integrates all components for CLI usage."""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from .agents.brainstorming import BrainstormingAgent
from .agents.interest import InterestAgent
from .config.database import DatabaseConfig
from .core.bus import EventBus
from .core.commands import Command
from .core.engine import Engine
from .ingest.pipeline import IngestPipeline
from .llm.openrouter import OpenRouterRuntime
from .store.knowledge import UnifiedKnowledgeStore
from .store.vector import KnowledgeBase


def utcnow() -> datetime:
    """Get current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


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
        self._knowledge_store: Optional[UnifiedKnowledgeStore] = None
        self._ingest: Optional[IngestPipeline] = None
        self._interest_agent: Optional[InterestAgent] = None
        self._brainstorming_agent: Optional[BrainstormingAgent] = None
        self._research_agent: Optional[Any] = None
        self._question_counter: dict[str, int] = {}
        self._question_batch_buffer: dict[str, list[str]] = {}

    async def initialize(self) -> None:
        """Initialize all components."""
        logger.info("=" * 60)
        logger.info("Initializing PersonalAssistantEngine...")
        logger.info("=" * 60)

        # Initialize LLM
        logger.info("[1/6] Initializing LLM runtime (OpenRouter)...")
        self._llm = OpenRouterRuntime(config=self.config)
        logger.info("      ✓ LLM runtime ready")

        # Initialize storage
        logger.info("[2/6] Initializing vector knowledge base (Qdrant)...")
        self._kb = KnowledgeBase(config=self.config, llm=self._llm)
        await self._kb.initialize()
        logger.info("      ✓ Vector DB ready")

        # Initialize unified knowledge store
        logger.info("[3/6] Initializing unified knowledge store...")
        db_config = DatabaseConfig.from_env()
        logger.info(f"      Using {db_config.db_type.upper()} backend")
        if db_config.db_type == "postgresql":
            logger.info(f"      Host: {db_config.postgresql_host}:{db_config.postgresql_port}")
        else:
            logger.info(f"      Path: {db_config.sqlite_path}")

        self._knowledge_store = UnifiedKnowledgeStore(
            db_type=db_config.db_type,
            **db_config.to_connection_kwargs()
        )
        await self._knowledge_store.initialize()
        logger.info("      ✓ Knowledge store ready")

        # Initialize ingest pipeline
        logger.info("[4/6] Initializing ingest pipeline...")
        self._ingest = IngestPipeline(self.config)
        logger.info("      ✓ Ingest pipeline ready")

        # Create core engine
        logger.info("[5/6] Creating core engine and registering agents...")
        self._engine = Engine(
            llm=self._llm,
            store=self._kb,
            memory=self._knowledge_store,
            graph=self._knowledge_store,
            ingest=self._ingest,
        )

        # Initialize Interest Agent
        logger.info("      • Initializing Interest Agent...")
        self._interest_agent = InterestAgent(
            engine=self._engine, llm=self._llm, memory=self._knowledge_store
        )
        self._engine.register_agent("interest", self._interest_agent)
        logger.info("        ✓ Interest Agent ready")

        # Initialize Brainstorming Agent
        logger.info("      • Initializing Brainstorming Agent...")
        self._brainstorming_agent = BrainstormingAgent(
            store=self._knowledge_store, llm=self._llm, config=self.config
        )
        self._engine.register_agent("brainstorm", self._brainstorming_agent)
        logger.info("        ✓ Brainstorming Agent ready")

        # Initialize Research Agent
        logger.info("      • Initializing Research Agent...")
        from .agents.research.agent import ResearchAgent

        self._research_agent = ResearchAgent(
            llm=self._llm, store=self._knowledge_store, config=self.config
        )
        self._engine.register_agent("research", self._research_agent)
        logger.info("        ✓ Research Agent ready")

        logger.info("[6/6] Engine startup complete")
        logger.info("=" * 60)
        logger.info("PersonalAssistantEngine ready. Type 'help' for commands.")
        logger.info("=" * 60)

    async def shutdown(self) -> None:
        """Clean shutdown of all components."""
        logger.info("Shutting down PersonalAssistantEngine...")

        if self._knowledge_store:
            logger.debug("Closing unified knowledge store...")
            await self._knowledge_store.close()

        logger.info("PersonalAssistantEngine shutdown complete")

    @property
    def bus(self) -> EventBus:
        """Get the event bus for streaming."""
        assert self._engine is not None
        return self._engine._bus

    @property
    def store(self) -> UnifiedKnowledgeStore:
        """Get the unified knowledge store (for read-only adapters/dashboards)."""
        assert self._knowledge_store is not None
        return self._knowledge_store

    async def submit(self, cmd: Command) -> str:
        """Submit a command to the core engine for async execution."""
        assert self._engine is not None
        return await self._engine.submit(cmd)

    async def process_activity_signals(self, signals: list, user_id: str = "local") -> list:
        """
        Run activity signals through the Interest Agent.

        Returns ResearchTopic commands for topics whose interest strength
        crossed the research trigger threshold. Caller is responsible for
        submitting them via `submit()`.
        """
        assert self._interest_agent is not None
        return await self._interest_agent.process_signals(signals, user_id=user_id)

    async def ask(self, query: str, user: str = "cli", session_id: Optional[str] = None) -> str:
        """Ask a question and return the answer."""
        import uuid
        from datetime import datetime

        assert self._engine is not None
        logger.info(f"Processing query: {query[:50]}...")

        if user not in self._question_counter:
            self._question_counter[user] = 0
            self._question_batch_buffer[user] = []

        if not session_id:
            session_id = f"{user}-{datetime.utcnow().strftime('%Y%m%d')}"

        if self._knowledge_store:
            await self._knowledge_store.get_or_create_session(session_id, user)
            await self._knowledge_store.add_conversation_turn(
                session_id=session_id, role="user", content=query, metadata={"type": "question"}
            )
            await self._knowledge_store.increment_user_question_count(user)

        self._question_batch_buffer[user].append(query)
        self._question_counter[user] += 1

        batch_size = self.config.get("agents", {}).get("interest", {}).get("batch_size", 5)
        extracted_interests = []

        if self._question_counter[user] >= batch_size:
            questions_batch = self._question_batch_buffer[user].copy()
            extracted_interests = await self._extract_interests_from_batch(questions_batch, user)
            self._question_counter[user] = 0
            self._question_batch_buffer[user] = []

        if not self._llm:
            raise RuntimeError("LLM not initialized")

        response = await self._llm.chat(
            messages=[{"role": "user", "content": query}],
            model_role="meta",
        )
        answer = response.content
        logger.debug(f"Query answered ({len(answer)} chars)")

        if self._knowledge_store:
            await self._knowledge_store.add_conversation_turn(
                session_id=session_id, role="assistant", content=answer, metadata={"type": "answer"}
            )

        quality_threshold = self.config.get("knowledge", {}).get("quality_threshold", 0.65)
        quality_score = await self._assess_answer_quality(query, answer)

        if quality_score >= quality_threshold and self._knowledge_store:
            entry_id = f"ka-{uuid.uuid4().hex[:12]}"
            await self._knowledge_store.store_knowledge_entry(
                entry_id=entry_id,
                question=query,
                answer=answer,
                quality_score=quality_score,
                user_id=user,
                session_id=session_id,
                metadata={"extracted_interests": extracted_interests, "auto_stored": True},
            )
            logger.info(f"Stored knowledge entry: {entry_id} (quality={quality_score:.2f})")

        return answer

    async def brainstorm(self, topic: str, user: str = "cli") -> str:
        """Start a brainstorming session."""
        assert self._brainstorming_agent is not None
        logger.info(f"Brainstorming topic: {topic}")

        result = await self._brainstorming_agent.answer(topic, user_id=user)
        logger.debug(f"Brainstorming completed ({len(result.text)} chars)")
        return result.text

    async def research(self, topic: str, depth: int = 2, user: str = "cli") -> str:
        """Research a topic using the Research Agent (citation graph + knowledge graph)."""
        assert self._research_agent is not None

        # Map numeric depth to string depth
        depth_map = {1: "shallow", 2: "normal", 3: "deep"}
        depth_str = depth_map.get(depth, "normal")

        logger.info(f"Researching topic: {topic} (depth={depth_str})")

        result = await self._research_agent.research(
            topic,
            depth=depth_str,
            trigger_source="manual",
        )

        summary = (
            f"Research completed: {result.new_papers} new papers, "
            f"{result.new_concepts} concepts discovered.\n\n{result.summary}"
        )
        logger.debug(f"Research completed ({len(summary)} chars)")
        return summary

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

        # Store activities in knowledge store
        if self._knowledge_store and result.signals:
            for signal in result.signals[:10]:  # Limit for now
                # Could classify and update interests here
                pass

        return stats

    async def get_interests(self, min_strength: float = 0.0) -> list[dict[str, Any]]:
        """Get user's current interests."""
        assert self._knowledge_store is not None
        logger.debug(f"Fetching interests (min_strength={min_strength})")

        interests = await self._knowledge_store.get_interests(min_strength=min_strength)
        logger.debug(f"Found {len(interests)} interests")
        return interests

    async def add_interest(self, label: str, strength: float = 0.5) -> None:
        """Manually add an interest."""
        from datetime import datetime

        assert self._knowledge_store is not None
        logger.info(f"Adding interest: {label} (strength={strength})")

        now = datetime.utcnow().isoformat()
        interest = {
            "id": label.lower().replace(" ", "-"),
            "label": label,
            "strength": strength,
            "created_at": now,
            "updated_at": now,
            "last_active": now,
        }
        await self._knowledge_store.upsert_interest(interest)
        logger.debug(f"Interest '{label}' added successfully")

    async def _extract_interests_from_batch(
        self, questions: list[str], user_id: str = "cli"
    ) -> list[str]:
        """Extract user interests from a batch of questions."""
        if not questions or not self._interest_agent:
            return []

        logger.info(f"Extracting interests from batch of {len(questions)} questions")

        from .daemon.connector_base import ActivitySignal

        aggregated_text = " | ".join([f"Q{i+1}: {q}" for i, q in enumerate(questions)])

        signal = ActivitySignal(
            source="user_questions",
            event_type="batch_query",
            data={"questions": questions, "aggregated": aggregated_text},
            timestamp=utcnow(),
        )

        try:
            research_commands = await self._interest_agent.process_signals(
                [signal], user_id=user_id
            )

            extracted_interests = [cmd.topic for cmd in research_commands]

            logger.info(f"Extracted {len(extracted_interests)} interests from question batch")
            return extracted_interests

        except Exception as e:
            logger.warning(f"Interest extraction failed: {e}")
            return []

    async def _assess_answer_quality(
        self, question: str, answer: str, min_length: int = 100
    ) -> float:
        """Assess if an answer is high-quality enough to store as knowledge."""
        if len(answer) < min_length:
            return 0.0

        filler_patterns = [
            "i think",
            "i believe",
            "in my opinion",
            "that's a great question",
            "thank you for asking",
            "as an ai",
            "as a language model",
        ]
        answer_lower = answer.lower()
        if any(pattern in answer_lower for pattern in filler_patterns):
            return 0.0

        if not self._llm:
            return 0.0

        quality_prompt = f"""Rate the quality of this Q&A pair for knowledge storage (0.0-1.0):

Question: {question}

Answer: {answer}

Criteria:
- Factual accuracy and specificity (not vague)
- Educational value (teaches something useful)
- Completeness (answers the full question)
- Verifiability (contains concrete information, not opinions)

Respond with ONLY a number between 0.0 and 1.0 (e.g., "0.75")."""

        try:
            response = await self._llm.chat(
                messages=[{"role": "user", "content": quality_prompt}],
                model_role="meta",
            )

            import re

            score_text = response.content.strip()
            match = re.search(r"(\d\.?\d*)", score_text)
            if match:
                score = float(match.group(1))
                return max(0.0, min(1.0, score))
            return 0.0

        except Exception as e:
            logger.warning(f"Quality assessment failed: {e}")
            return 0.0


# Factory function
def create_engine(config: dict[str, Any]) -> PersonalAssistantEngine:
    """Create and initialize a PA engine."""
    return PersonalAssistantEngine(config)
