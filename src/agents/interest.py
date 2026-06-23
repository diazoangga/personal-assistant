"""Interest Agent - Classifies activity signals into interests and triggers research."""

import json
import logging
from typing import Any

from ..core.commands import ResearchTopic
from ..core.signals import InterestClassification
from ..daemon.connector_base import ActivitySignal
from ..store.knowledge import UnifiedKnowledgeStore

logger = logging.getLogger(__name__)


class InterestAgent:
    """
    Consumes activity signals and maintains user interest model.

    Flow:
    1. Receive batch of signals from connectors
    2. Classify each into topics (via LLM)
    3. Update interest graph
    4. Detect strengthened topics
    5. Emit ResearchTopic commands for new/strengthened interests
    """

    def __init__(self, engine: Any, llm: Any, memory: UnifiedKnowledgeStore, config: dict[str, Any] | None = None):
        self.engine = engine  # to submit ResearchTopic commands
        self.llm = llm  # to classify signals
        self.memory = memory
        self.config = config or {}
        self.embedding_model = self.config.get("llm", {}).get("embedding_model", "qwen/qwen3-embedding-8b")
        self.logger = logging.getLogger(__name__)

    async def process_signals(
        self, signals: list[ActivitySignal], user_id: str = "local"
    ) -> list[ResearchTopic]:
        """
        Main entry point. Process signals and return research topics to trigger.

        Steps:
        1. Classify signals → InterestSignal objects
        2. Store in interest graph
        3. Calculate interest strengths
        4. Compare to previous → find strengthened
        5. Emit ResearchTopic commands
        """
        if not signals:
            return []

        self.logger.info(f"Processing {len(signals)} signals for user {user_id}")

        try:
            # Step 1: Classify signals
            classified = await self._classify_signals(signals)
            self.logger.debug(f"Classified {len(classified)} signals")

            # Step 2: Store in interest graph
            for classification in classified:
                if classification.is_valid():
                    for topic, confidence in zip(
                        classification.topics, classification.confidences
                    ):
                        await self.memory.add_classified_signal(
                            signal_id=classification.signal_id,
                            topic=topic,
                            confidence=confidence,
                            timestamp=classification.timestamp.isoformat(),
                        )
            self.logger.debug("Stored classifications in interest graph")

            # Step 3: Detect research triggers
            research_topics = await self._detect_research_triggers(
                user_id, classified
            )
            self.logger.info(
                f"Detected {len(research_topics)} research triggers"
            )

            return research_topics

        except Exception as e:
            self.logger.error(f"Error processing signals: {e}", exc_info=True)
            return []

    async def _classify_signals(
        self, signals: list[ActivitySignal]
    ) -> list[InterestClassification]:
        """
        Classify signals using hybrid approach: semantic similarity + LLM fallback.
        
        1. Embed signal text
        2. Compare to existing interest embeddings (if available)
        3. If top-2 matches > 0.6 threshold → use them (skip LLM)
        4. Else → call LLM for new topics
        
        This reduces LLM calls by ~70% once interest model is established.
        """
        classified = []
        
        # Get existing interest embeddings (strength > 0.2)
        interest_embs = await self.memory.get_interest_embeddings(min_strength=0.2)
        
        for signal in signals:
            try:
                text = self._signal_to_text(signal)
                
                # Step 1: Try semantic matching with existing interests
                matched_topics = []
                signal_embedding = None
                
                if interest_embs:
                    # Embed the signal text
                    signal_embedding = await self.llm.embed([text])
                    
                    # Compute similarities to all cached interest embeddings
                    matches = []
                    for interest_id, interest_emb, _ in interest_embs:
                        similarity = self.memory.cosine_similarity(
                            signal_embedding[0], interest_emb
                        )
                        if similarity > 0.6:  # Threshold for match
                            matches.append((interest_id, similarity))
                    
                    # Take top 2 matches
                    matches.sort(key=lambda x: x[1], reverse=True)
                    top_matches = matches[:2]
                    
                    if top_matches:
                        matched_topics = [(m[0], m[1]) for m in top_matches]
                        self.logger.debug(
                            f"Semantic match for {signal.source}: {[t[0] for t in matched_topics]}"
                        )
                
                # Step 2: Use matched topics or fall back to LLM
                if matched_topics:
                    # Use semantic matches (no LLM call needed)
                    classification = InterestClassification(
                        signal_id=f"{signal.source}_{signal.timestamp.timestamp()}",
                        topics=[t[0] for t in matched_topics],
                        confidences=[t[1] for t in matched_topics],
                        explanation=f"Semantic similarity match (scores: {[round(t[1], 2) for t in matched_topics]})",
                        model_version="hybrid-v1",
                        timestamp=signal.timestamp,
                    )
                    classified.append(classification)
                    
                    # Update embedding cache with this signal's embedding
                    if signal_embedding and len(matched_topics) > 0:
                        await self.memory.upsert_interest_embedding(
                            interest_id=matched_topics[0][0],
                            embedding=signal_embedding[0],
                            model_version=self.embedding_model,
                        )
                
                else:
                    # No semantic match → use LLM
                    llm_classification = await self._classify_with_llm(signal, text)
                    if llm_classification:
                        classified.append(llm_classification)
                        
                        # Cache embedding for new topic
                        if signal_embedding is None:
                            signal_embedding = await self.llm.embed([text])
                        
                        # Cache embedding for the primary topic
                        await self.memory.upsert_interest_embedding(
                            interest_id=llm_classification.topics[0],
                            embedding=signal_embedding[0],
                            model_version=self.embedding_model,
                        )
                        
            except Exception as e:
                self.logger.error(f"Error classifying signal: {e}", exc_info=True)
        
        return classified

    async def _classify_with_llm(
        self, signal: ActivitySignal, text: str
    ) -> InterestClassification | None:
        """
        Classify a signal using LLM (fallback when semantic matching fails).
        
        Returns InterestClassification or None if classification fails.
        """
        try:
            prompt = f"""Analyze this activity and extract the main topics/interests it represents.
Respond with a JSON object containing:
- "topics": list of strings (e.g., ["machine learning", "python"])
- "confidences": list of floats 0-1 (confidence for each topic)
- "explanation": brief explanation

Activity: {text}

Respond with valid JSON only."""

            response = await self.llm.complete(
                role="reasoning", prompt=prompt, max_tokens=256, temperature=0.3
            )

            # Parse response
            try:
                data = json.loads(response)
                topics = data.get("topics", [])
                confidences = data.get("confidences", [])
                explanation = data.get("explanation", "")

                # Validate
                if len(topics) > 0 and len(topics) == len(confidences):
                    classification = InterestClassification(
                        signal_id=f"{signal.source}_{signal.timestamp.timestamp()}",
                        topics=topics,
                        confidences=confidences,
                        explanation=explanation,
                        model_version="llm-v1",
                        timestamp=signal.timestamp,
                    )
                    self.logger.debug(
                        f"LLM classified {signal.source} → {topics}"
                    )
                    return classification
                else:
                    self.logger.warning(
                        f"Invalid LLM classification response: {data}"
                    )
                    return None

            except json.JSONDecodeError as e:
                self.logger.warning(f"Failed to parse LLM response: {e}")
                return None
                
        except Exception as e:
            self.logger.error(f"Error in LLM classification: {e}", exc_info=True)
            return None

    async def _detect_research_triggers(
        self,
        user_id: str,
        classifications: list[InterestClassification],
    ) -> list[ResearchTopic]:
        """
        Compare new strength to old strength.
        Emit ResearchTopic if increased by threshold.
        """
        research_topics = []

        # Get all topics from classifications
        all_topics = set()
        for c in classifications:
            all_topics.update(c.topics)

        # For each topic, check if it should trigger research
        for topic in all_topics:
            try:
                # Check cooldown
                if not await self.memory.should_research(topic, cooldown_hours=24):
                    self.logger.debug(f"Topic '{topic}' on cooldown")
                    continue

                # Get current strength
                strength = await self.memory.get_strength(topic)

                # Trigger if strength > 0.3 (significant interest)
                if strength > 0.3:
                    self.logger.info(
                        f"Research trigger: {topic} (strength={strength:.2f})"
                    )

                    # Mark as researched to prevent duplicate triggers
                    await self.memory.mark_researched(topic)

                    # Create research topic command
                    research_topic = ResearchTopic(
                        user=user_id,
                        topic=topic,
                        depth="normal" if strength < 0.7 else "deep",
                    )
                    research_topics.append(research_topic)

            except Exception as e:
                self.logger.error(
                    f"Error detecting trigger for {topic}: {e}", exc_info=True
                )

        return research_topics

    def _signal_to_text(self, signal: ActivitySignal) -> str:
        """Convert an ActivitySignal to human-readable text for LLM."""
        parts = []

        # Source
        source = signal.source  # "github", "browser", "slack"
        parts.append(f"Source: {source}")

        # Event type
        event_type = signal.event_type  # "commit", "search", "message"
        parts.append(f"Type: {event_type}")

        # Data-specific text
        data = signal.data or {}

        if source == "github":
            if event_type == "commit":
                parts.append(f"Repo: {data.get('repository', 'unknown')}")
                parts.append(f"Message: {data.get('message', '')}")
            elif event_type == "pull_request":
                parts.append(f"Repo: {data.get('repository', 'unknown')}")
                parts.append(f"Title: {data.get('title', '')}")

        elif source == "browser":
            if event_type == "search":
                parts.append(f"Query: {data.get('query', '')}")
                parts.append(f"Engine: {data.get('engine', '')}")
            elif event_type == "page_visit":
                parts.append(f"Domain: {data.get('domain', '')}")
                parts.append(f"Title: {data.get('title', '')}")

        elif source == "slack":
            if event_type == "message":
                parts.append(f"Channel: {data.get('channel', '')}")
                parts.append(f"Text: {data.get('text', '')[:100]}")

        return " | ".join(parts)
