#!/usr/bin/env python3
"""Test script for unified knowledge store and hybrid classification."""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.store.knowledge import UnifiedKnowledgeStore


async def test_unified_store():
    """Test basic operations of the unified knowledge store."""
    print("=" * 60)
    print("Testing Unified Knowledge Store")
    print("=" * 60)
    
    store = UnifiedKnowledgeStore("./data/test_knowledge.db")
    
    try:
        await store.initialize()
        print("[OK] Database initialized successfully")
        
        # Test interest operations
        print("\n--- Testing Interest Operations ---")
        interest = {
            "id": "machine-learning",
            "label": "Machine Learning",
            "strength": 0.8,
            "created_at": "2026-06-21T00:00:00",
            "updated_at": "2026-06-21T00:00:00",
            "last_active": "2026-06-21T00:00:00",
        }
        await store.upsert_interest(interest)
        print("[OK] Added interest")
        
        interests = await store.get_interests(min_strength=0.5)
        assert len(interests) == 1
        print(f"[OK] Retrieved {len(interests)} interest(s)")
        
        # Test concept operations
        print("\n--- Testing Concept Operations ---")
        concept = {
            "id": "ml-concept",
            "label": "Machine Learning",
            "description": "A subset of AI",
            "category": "technology",
            "created_at": "2026-06-21T00:00:00",
        }
        await store.upsert_concept(concept)
        print("[OK] Added concept")
        
        concepts = await store.get_all_concepts()
        assert len(concepts) == 1
        print(f"[OK] Retrieved {len(concepts)} concept(s)")
        
        # Test linking
        print("\n--- Testing Interest-Concept Linking ---")
        await store.link_interest_to_concept(
            "machine-learning",
            "ml-concept",
            link_type="exact_match",
            confidence=1.0,
        )
        print("[OK] Created interest-concept link")
        
        linked_concepts = await store.get_linked_concepts_for_interest("machine-learning")
        assert len(linked_concepts) == 1
        print(f"[OK] Retrieved {len(linked_concepts)} linked concept(s)")
        
        # Test citation operations
        print("\n--- Testing Citation Operations ---")
        citation = {
            "id": "test-paper-1",
            "arxiv_id": "2301.12345",
            "title": "Test Paper on ML",
            "abstract": "This is a test abstract",
            "authors": '["Author One", "Author Two"]',
            "published_date": "2026-01-15",
            "journal": "Test Journal",
            "categories": '["cs.AI", "cs.LG"]',
            "citation_count": 10,
        }
        await store.upsert_citation(citation)
        print("[OK] Added citation")
        
        # Test citation-concept linking
        await store.link_citation_to_concept(
            "test-paper-1",
            "ml-concept",
            relation_type="discusses",
            evidence_text="The paper discusses ML techniques",
        )
        print("[OK] Created citation-concept link")
        
        linked_citations = await store.get_linked_citations_for_concept("ml-concept")
        assert len(linked_citations) == 1
        print(f"[OK] Retrieved {len(linked_citations)} linked citation(s)")
        
        # Test embedding cache (mock embedding)
        print("\n--- Testing Embedding Cache ---")
        import struct
        mock_embedding = struct.pack('384f', *[0.1] * 384)  # Mock 384-dim embedding
        
        await store.upsert_interest_embedding(
            "machine-learning",
            mock_embedding,
            "qwen/qwen3-embedding-8b",
        )
        print("[OK] Cached interest embedding")
        
        embeddings = await store.get_interest_embeddings(min_strength=0.5)
        assert len(embeddings) == 1
        print(f"[OK] Retrieved {len(embeddings)} embedding(s)")
        
        # Test interest signal evidence
        print("\n--- Testing Interest Signal Evidence ---")
        await store.add_classified_signal(
            signal_id="test-signal-1",
            topic="machine-learning",
            confidence=0.9,
            timestamp="2026-06-21T00:00:00",
        )
        print("[OK] Added classified signal")
        
        strength = await store.get_strength("machine-learning")
        print(f"[OK] Computed interest strength: {strength:.4f}")
        
        # Test research tracking
        print("\n--- Testing Research Tracking ---")
        should_research = await store.should_research("machine-learning", cooldown_hours=24)
        print(f"[OK] Should research: {should_research}")
        
        await store.mark_researched("machine-learning")
        print("[OK] Marked topic as researched")
        
        should_research_again = await store.should_research("machine-learning", cooldown_hours=24)
        print(f"[OK] Should research again (within cooldown): {should_research_again}")
        
        # Get stats
        print("\n--- Final Statistics ---")
        stats = await store.get_stats()
        for table, count in stats.items():
            print(f"  {table}: {count}")
        
        print("\n" + "=" * 60)
        print("All tests passed!")
        print("=" * 60)
        
    finally:
        await store.close()
        # Clean up test database
        test_db = Path("./data/test_knowledge.db")
        if test_db.exists():
            test_db.unlink()
            print("\nCleaned up test database")


if __name__ == "__main__":
    asyncio.run(test_unified_store())
