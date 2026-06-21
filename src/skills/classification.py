"""Classification skill - classify intent and activity."""

from dataclasses import dataclass
from typing import Any


@dataclass
class IntentClassification:
    """Result of intent classification."""

    intent: str  # "ask", "brainstorm", "research", "opportunities", "feedback"
    confidence: float
    topics: list[str]
    urgency: str  # "low", "medium", "high"


@dataclass
class ActivityClassification:
    """Result of activity classification."""

    category: str  # "coding", "reading", "meeting", "writing", "research"
    topics: list[str]
    learning_signal: bool  # Is this a learning activity?
    achievement_signal: bool  # Is this an achievement?


async def classify_intent(
    text: str, llm: Any
) -> IntentClassification:
    """
    Classify user intent from natural language.

    Args:
        text: User input text
        llm: LLM runtime with chat() method

    Returns:
        IntentClassification result
    """
    prompt = f"""Classify the user's intent into one of these categories:
- ask: Asking a question or seeking information
- brainstorm: Wanting to explore ideas or think through something
- research: Requesting deep research on a topic
- opportunities: Looking for career/learning opportunities
- feedback: Providing feedback on previous outputs

Also extract topics and assess urgency (low/medium/high).

Return ONLY a JSON object with this structure:
{{
    "intent": "category",
    "confidence": 0.95,
    "topics": ["topic1", "topic2"],
    "urgency": "medium"
}}

User input:
{text}

Classification:"""

    response = await llm.chat(
        messages=[{"role": "user", "content": prompt}],
        model_role="meta",
    )

    import json

    content = response.content.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    try:
        data = json.loads(content)
        return IntentClassification(
            intent=data.get("intent", "ask"),
            confidence=data.get("confidence", 0.5),
            topics=data.get("topics", []),
            urgency=data.get("urgency", "medium"),
        )
    except json.JSONDecodeError:
        return IntentClassification(
            intent="ask",
            confidence=0.3,
            topics=[],
            urgency="medium",
        )


async def classify_activity(
    description: str, llm: Any
) -> ActivityClassification:
    """
    Classify a user activity from its description.

    Args:
        description: Activity description (e.g., GitHub commit message)
        llm: LLM runtime with chat() method

    Returns:
        ActivityClassification result
    """
    prompt = f"""Classify this user activity:

{description}

Categories: coding, reading, meeting, writing, research, other

Return ONLY a JSON object:
{{
    "category": "coding",
    "topics": ["python", "api"],
    "learning_signal": true,
    "achievement_signal": true
}}

Classification:"""

    response = await llm.chat(
        messages=[{"role": "user", "content": prompt}],
        model_role="meta",
    )

    import json

    content = response.content.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    try:
        data = json.loads(content)
        return ActivityClassification(
            category=data.get("category", "other"),
            topics=data.get("topics", []),
            learning_signal=data.get("learning_signal", False),
            achievement_signal=data.get("achievement_signal", False),
        )
    except json.JSONDecodeError:
        return ActivityClassification(
            category="other",
            topics=[],
            learning_signal=False,
            achievement_signal=False,
        )
