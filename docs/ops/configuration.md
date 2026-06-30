# Configuration

Configuration is **environment-driven** (`.env`). `config/settings.toml` documents the
structure and defaults but is reference-only — the running app reads env vars and the
config dict assembled by the CLI/API loader.

## Environment variables

**Required**
| Var | Purpose |
|---|---|
| `OPENROUTER_API_KEY` | LLM + embeddings |
| `GITHUB_TOKEN` | GitHub connector |

**Optional**
| Var | Default | Purpose |
|---|---|---|
| `SLACK_BOT_TOKEN` | — | Slack connector |
| `TAVILY_API_KEY` | — | Brainstorming web search |
| `LOCAL_API_HOST` / `LOCAL_API_PORT` | `127.0.0.1` / `8787` | web API bind |
| `LOCAL_API_TOKEN` | — | optional bearer for the web API |
| `LOCAL_API_USER` | `local` | single-user identity |
| `DB_TYPE` + `DB_*` | `sqlite` | relational backend — see [storage/postgres.md](../storage/postgres.md) |

## settings.toml sections (defaults)

| Section | Key settings |
|---|---|
| `[llm]` | `meta_model`, `reasoning_model`, `embedding_model`, `rate_limit_per_minute` (60), `rate_limit_per_day` (1000), `max_retries` (3) |
| `[storage]` | `qdrant_host/port/collection`, `knowledge_db` |
| `[agents.interest]` | `batch_size` (5), `min_confidence` (0.6), `embedding_cache_enabled` |
| `[agents.brainstorming]` | `temperature` (0.7), `max_iterations` (5) |
| `[knowledge]` | `quality_threshold` (0.65), `max_entries_per_user` (1000) |
| `[daemon]` | `check_interval_seconds` (60), `ingest_interval_minutes` (15), log/pid/state files |
| `[connectors.github]` | `enabled = true` |
| `[connectors.slack]` / `[connectors.browser]` | `enabled = false` (opt-in) |
| `[topics]` | `seed_topics` |

## Thresholds that shape behaviour

| Setting | Effect |
|---|---|
| interest `strength_threshold` 0.3 | crossing it triggers research ([signal-flow](../architecture/signal-flow.md)) |
| 720 h decay constant | interest half-life ≈ 30 days |
| 24 h research cooldown | prevents duplicate triggers per topic |
| `quality_threshold` 0.65 | minimum to auto-save a Q&A as a `knowledge_entry` |
| `min_entity_confidence` 0.6 | concept-extraction noise floor |
| `max_citation_depth` 2 | citation-graph BFS depth (exponential cost) |

---

> **Source of truth:** `config/settings.toml`, `.env.example`, `src/config/database.py`,
> `src/adapters/{cli,api}`.
