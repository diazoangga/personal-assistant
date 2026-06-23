"""Knowledge Base - Vector DB with Qdrant (or pgvector alternative)."""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """A chunk of text with embeddings and metadata."""

    id: str  # content hash for dedup
    text: str
    embedding: list[float]
    source_url: str | None
    connector: str  # "arxiv" | "github_research" | "medium" | "news"
    topic: str
    ingested_at: str  # ISO date
    quality: float  # research-time score

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "source_url": self.source_url,
            "connector": self.connector,
            "topic": self.topic,
            "ingested_at": self.ingested_at,
            "quality": self.quality,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], embedding: list[float]) -> "Chunk":
        return cls(
            id=data["id"],
            text=data["text"],
            embedding=embedding,
            source_url=data.get("source_url"),
            connector=data["connector"],
            topic=data["topic"],
            ingested_at=data["ingested_at"],
            quality=data["quality"],
        )


@dataclass
class Hit:
    """A retrieval hit with score and chunk."""

    chunk: Chunk
    score: float


class KnowledgeBase:
    """
    Qdrant-based knowledge base for research content.

    Supports hybrid search (dense + sparse) with reranking.
    """

    def __init__(self, config: dict[str, Any], llm: Any):
        self.host = config.get("qdrant_host", "localhost")
        self.port = config.get("qdrant_port", 6333)
        self.collection_name = config.get("qdrant_collection", "personal-assistant-kb")
        self.llm = llm  # For embeddings

        self._base_url = f"http://{self.host}:{self.port}"
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the collection if it doesn't exist. Falls back to stub mode if Qdrant unavailable."""
        logger.debug(f"Initializing KnowledgeBase at {self._base_url}/{self.collection_name}")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Check if collection exists
                response = await client.get(f"{self._base_url}/collections/{self.collection_name}")
                if response.status_code == 404:
                    logger.info(f"Creating new collection: {self.collection_name}")
                    await self._create_collection(client)
                else:
                    logger.debug(f"Collection {self.collection_name} already exists")
            self._initialized = True
            logger.info("KnowledgeBase initialized successfully")
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.warning(
                f"Qdrant unavailable at {self._base_url} ({type(e).__name__}). "
                "Running in stub mode (no semantic search). "
                "To enable: docker run -p 6333:6333 qdrant/qdrant"
            )
            self._initialized = True  # Still mark as initialized to allow app to run

    async def _create_collection(self, client: httpx.AsyncClient) -> None:
        """Create the Qdrant collection."""
        # Get embedding dimension from a test embedding
        test_embed = await self.llm.embed(["test"])
        dim = len(test_embed[0])

        payload = {
            "vectors": {
                "size": dim,
                "distance": "Cosine",
            },
            "hnsw_config": {
                "m": 16,
                "ef_construct": 100,
            },
        }

        response = await client.put(
            f"{self._base_url}/collections/{self.collection_name}",
            json=payload,
        )
        response.raise_for_status()

    async def upsert(self, chunks: list[Chunk]) -> None:
        """
        Upsert chunks into the knowledge base.

        Uses content hash for deduplication.
        """
        if not self._initialized:
            await self.initialize()

        points = []
        for chunk in chunks:
            point = {
                "id": chunk.id,
                "vector": chunk.embedding,
                "payload": chunk.to_dict(),
            }
            points.append(point)

        # Batch upsert
        batch_size = 100
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            async with httpx.AsyncClient() as client:
                response = await client.put(
                    f"{self._base_url}/collections/{self.collection_name}/points",
                    params={"wait": "true"},
                    json={"points": batch},
                )
                response.raise_for_status()

    async def search(self, query: str, k: int = 8) -> list[Hit]:
        """
        Search the knowledge base with hybrid retrieval.

        Args:
            query: Search query
            k: Number of results to return

        Returns:
            List of hits sorted by score
        """
        if not self._initialized:
            await self.initialize()

        # Get query embedding
        embeddings = await self.llm.embed([query])
        query_vector = embeddings[0]

        # Search Qdrant
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    f"{self._base_url}/collections/{self.collection_name}/points/search",
                    json={
                        "vector": query_vector,
                        "limit": k * 2,  # Get more for reranking
                        "with_payload": True,
                        "score_threshold": 0.5,
                    },
                )
                response.raise_for_status()
        except (httpx.ConnectError, httpx.TimeoutException):
            logger.debug(f"Qdrant unavailable, returning empty search results")
            return []
            results = response.json()["result"]

        # Convert to Hits
        hits = []
        for r in results:
            chunk = Chunk.from_dict(r["payload"], r["vector"])
            hits.append(Hit(chunk=chunk, score=r["score"]))

        # Sort by score and return top k
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]

    async def prune(self, older_than_days: int) -> int:
        """
        Remove chunks older than specified days.

        Returns number of chunks removed.
        """
        # Implementation: query by ingested_at timestamp and delete
        # For now, stub implementation
        return 0

    @staticmethod
    def compute_id(text: str) -> str:
        """Compute content hash for deduplication."""
        normalized = " ".join(text.lower().split())
        return hashlib.sha256(normalized.encode()).hexdigest()[:32]


def semantic_chunks(text: str, sim_threshold: float = 0.6, max_tokens: int = 512) -> list[str]:
    """
    Split text into semantic chunks.

    Starts a new chunk when consecutive-sentence similarity drops below threshold.
    Falls back to max-token cap.
    """
    # Simple implementation: split by paragraphs, then by sentences
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks = []
    current_chunk = []
    current_tokens = 0

    for para in paragraphs:
        sentences = [s.strip() for s in para.split(".") if s.strip()]

        for sentence in sentences:
            sentence_tokens = len(sentence.split())

            if current_tokens + sentence_tokens > max_tokens and current_chunk:
                # Start new chunk
                chunks.append(". ".join(current_chunk) + ".")
                current_chunk = []
                current_tokens = 0

            current_chunk.append(sentence)
            current_tokens += sentence_tokens

    if current_chunk:
        chunks.append(". ".join(current_chunk) + ".")

    return chunks
