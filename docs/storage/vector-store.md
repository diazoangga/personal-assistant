# Vector Store (Qdrant)

Semantic search over knowledge entries lives in **Qdrant**, wrapped by `KnowledgeBase`
(`store/vector.py`). It is separate from the relational [Unified Knowledge
Store](knowledge-store.md): the relational store is the system of record; Qdrant is a
derived index for similarity queries.

## Shape

| Concern | Value |
|---|---|
| Engine | Qdrant (qdrant-client, async) |
| Host/port | `storage.qdrant_host:qdrant_port` (default `localhost:6333`) |
| Collection | `storage.qdrant_collection` (default `personal-assistant-kb`) |
| Embeddings | via `OpenRouterRuntime.embed` (`qwen/qwen3-embedding-8b`) |
| Lifecycle | `KnowledgeBase(config, llm)` then `await initialize()` (creates the collection) |

`KnowledgeBase` is constructed in `main_engine.py` and passed to the engine as `store`
(the vector KB), distinct from `memory`/`graph` (the relational store).

## Running Qdrant

```bash
docker run -p 6333:6333 -p 6334:6334 qdrant/qdrant
# or: docker compose up -d   (see docker-compose.yml)
```

For tests, the vector DB is stubbed — unit tests don't require a live Qdrant.

## Open question

Production isolation model — one collection per user vs a shared collection with payload
filters — is undecided. For a single-user local app the single shared collection is fine;
revisit before any multi-user deployment.

---

> **Source of truth:** `src/store/vector.py`, `docker-compose.yml`, `config/settings.toml`
> (`[storage]`).
