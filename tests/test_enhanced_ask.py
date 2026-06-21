"""Test enhanced ask flow with conversation tracking, batch interest extraction, and knowledge storage."""

import asyncio
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_conversation_sessions():
    """Test conversation session management."""
    from src.store.knowledge import UnifiedKnowledgeStore
    
    store = UnifiedKnowledgeStore("./data/test_knowledge.db")
    await store.initialize()
    
    try:
        session_id = "test-session-001"
        user_id = "test-user"
        
        await store.create_conversation_session(session_id, user_id)
        logger.info(f"✓ Created session: {session_id}")
        
        turn1 = await store.add_conversation_turn(
            session_id=session_id,
            role="user",
            content="What is machine learning?",
            metadata={"type": "question"}
        )
        logger.info(f"✓ Added user turn {turn1}")
        
        turn2 = await store.add_conversation_turn(
            session_id=session_id,
            role="assistant",
            content="Machine learning is a subset of AI...",
            metadata={"type": "answer"}
        )
        logger.info(f"✓ Added assistant turn {turn2}")
        
        history = await store.get_conversation_history(session_id)
        logger.info(f"✓ Retrieved {len(history)} turns from history")
        
        session_info = await store.get_session_info(session_id)
        logger.info(f"✓ Session info: question_count={session_info['question_count']}")
        
        total_questions = await store.increment_user_question_count(user_id)
        logger.info(f"✓ User question count: {total_questions}")
        
        print("\n[PASS] Conversation sessions test PASSED\n")
        
    finally:
        await store.close()


async def test_knowledge_entries():
    """Test knowledge entry storage."""
    from src.store.knowledge import UnifiedKnowledgeStore
    
    store = UnifiedKnowledgeStore("./data/test_knowledge.db")
    await store.initialize()
    
    try:
        entry_id = "test-ka-001"
        
        await store.store_knowledge_entry(
            entry_id=entry_id,
            question="What is Python?",
            answer="Python is a high-level programming language...",
            quality_score=0.85,
            user_id="test-user",
            session_id="test-session-001",
            metadata={"auto_stored": True}
        )
        logger.info(f"✓ Stored knowledge entry: {entry_id}")
        
        entries = await store.get_knowledge_entries(min_quality=0.5, limit=10)
        logger.info(f"✓ Retrieved {len(entries)} knowledge entries")
        
        search_results = await store.search_knowledge_entries("Python", limit=5)
        logger.info(f"✓ Search returned {len(search_results)} results")
        
        stats = await store.get_user_stats("test-user")
        logger.info(f"✓ User stats: {stats}")
        
        print("\n[PASS] Knowledge entries test PASSED\n")
        
    finally:
        await store.close()


async def test_batch_tracking():
    """Test question counter and batch buffer."""
    from src.main_engine import PersonalAssistantEngine
    
    config = {
        "llm": {"provider": "openrouter"},
        "agents": {"interest": {"batch_size": 3}},
        "knowledge": {"quality_threshold": 0.65},
    }
    
    engine = PersonalAssistantEngine(config)
    
    assert engine._question_counter == {}, "Counter should start empty"
    assert engine._question_batch_buffer == {}, "Buffer should start empty"
    logger.info("✓ Batch tracking initialized correctly")
    
    print("\n[PASS] Batch tracking test PASSED\n")


async def main():
    """Run all tests."""
    print("=" * 60)
    print("ENHANCED ASK FLOW TESTS")
    print("=" * 60)
    
    try:
        await test_conversation_sessions()
        await test_knowledge_entries()
        await test_batch_tracking()
        
        print("=" * 60)
        print("ALL TESTS PASSED")
        print("=" * 60)
        
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        print("\n[FAIL] TESTS FAILED\n")
        raise


if __name__ == "__main__":
    asyncio.run(main())
