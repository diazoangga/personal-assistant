"""Engine wrapper - integrates all components for CLI usage."""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from .agents.interest import InterestAgent
from .core.commands import Command
from .core.engine import Engine
from .core.bus import EventBus
from .store.vector import KnowledgeBase
from .store.knowledge import UnifiedKnowledgeStore
from .ingest.pipeline import IngestPipeline
from .llm.openrouter import OpenRouterRuntime


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
        self._question_counter: dict[str, int] = {}
        self._question_batch_buffer: dict[str, list[str]] = {}

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
        
        # Initialize unified knowledge store
        knowledge_db = self.config.get("knowledge_db", "./data/knowledge.db")
        logger.debug(f"Initializing unified knowledge store (db={knowledge_db})...")
        self._knowledge_store = UnifiedKnowledgeStore(knowledge_db)
        await self._knowledge_store.initialize()
        
        # Initialize ingest pipeline
        logger.debug("Initializing ingest pipeline...")
        self._ingest = IngestPipeline(self.config)
        
        # Create core engine (with stub agents for now)
        logger.debug("Creating core engine...")
        self._engine = Engine(
            llm=self._llm,
            store=self._kb,
            memory=self._knowledge_store,
            graph=self._knowledge_store,
            ingest=self._ingest,
        )

        # Initialize Interest Agent (signal flow: classify activity -> research triggers)
        logger.debug("Initializing Interest Agent...")
        self._interest_agent = InterestAgent(engine=self._engine, llm=self._llm, memory=self._knowledge_store)

        logger.info("PersonalAssistantEngine initialized successfully")

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

    async def submit(self, cmd: Command) -> str:
        """Submit a command to the core engine for async execution."""
        assert self._engine is not None
        return await self._engine.submit(cmd)

    async def process_activity_signals(
        self, signals: list, user_id: str = "local"
    ) -> list:
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
        from .core.commands import Ask
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
                session_id=session_id,
                role="user",
                content=query,
                metadata={"type": "question"}
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
                session_id=session_id,
                role="assistant",
                content=answer,
                metadata={"type": "answer"}
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
                metadata={
                    "extracted_interests": extracted_interests,
                    "auto_stored": True
                }
            )
            logger.info(f"Stored knowledge entry: {entry_id} (quality={quality_score:.2f})")
        
        return answer

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
        self,
        questions: list[str],
        user_id: str = "cli"
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
        self,
        question: str,
        answer: str,
        min_length: int = 100
    ) -> float:
        """Assess if an answer is high-quality enough to store as knowledge."""
        if len(answer) < min_length:
            return 0.0
        
        filler_patterns = [
            "i think", "i believe", "in my opinion",
            "that's a great question", "thank you for asking",
            "as an ai", "as a language model"
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
            match = re.search(r'(\d\.?\d*)', score_text)
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
