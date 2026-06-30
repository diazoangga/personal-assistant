# Local Development

## Prerequisites

- Python ≥ 3.10, **Poetry** (the project uses a Poetry-managed `.venv`)
- `OPENROUTER_API_KEY` (free tier) and `GITHUB_TOKEN`
- Docker (for Qdrant; optional Postgres)

## Setup

```bash
poetry install
cp .env.example .env          # then edit: OPENROUTER_API_KEY, GITHUB_TOKEN, …
docker compose up -d          # Qdrant (+ Postgres if configured)
```

Configuration is **env-driven**; `config/settings.toml` is a reference for defaults only
(see [configuration.md](configuration.md)).

## Running

```bash
# CLI
poetry run pa ask "What am I interested in?"
poetry run pa interests
poetry run pa brainstorm

# Local web API (engine + daemon in one process, serves 127.0.0.1:8787, docs at /docs)
poetry run python -m src.adapters.api

# Daemon standalone
poetry run pa daemon start
poetry run pa daemon logs -f
poetry run pa daemon stop
```

The desktop app expects the web API on `:8787` — start it before
`pnpm tauri dev` in `personal-assistant-desktop`.

## Testing

Always go through Poetry — `pytest-asyncio`/`pytest-cov` are only in the Poetry `.venv`,
not the global interpreter.

```bash
poetry run pytest tests/                                  # all
poetry run pytest tests/test_signal_flow.py -v            # Interest/signal flow
poetry run pytest tests/test_research_agent.py -v         # Research pipeline
poetry run pytest tests/test_brainstorming_agent.py -v    # Brainstorming
poetry run pytest tests/ --cov=src                        # coverage
```

Tests use temporary SQLite DBs (`tempfile.mkstemp`), mock the LLM (`FakeLLM`), and mock
connectors — no live network or real `data/knowledge.db`. `asyncio_mode = "auto"`.

## Lint / format / types

```bash
poetry run black src/ tests/ && poetry run ruff check src/ && poetry run mypy src/
```

---

> **Source of truth:** `pyproject.toml`, `docker-compose.yml`, `tests/`, project `CLAUDE.md`.
