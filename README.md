# Personal Assistant

AI Personal Assistant powered by OpenRouter (Gemma4-31B free tier) with continuous cognitive engine architecture.

## Features

- **Continuous sensing**: Monitors your activities (GitHub, browser, Slack, calendar)
- **Interest modeling**: Builds and maintains a model of your evolving interests
- **Deep research**: Automatically researches papers, GitHub repos, articles on topics you care about
- **Proactive insights**: Generates ranked recommendations and ideas with full provenance
- **Interactive brainstorming**: Ask anything, get cited answers, ideate with traceable proposals
- **Symmetric interfaces**: CLI and Slack use the same engine

## Architecture

5 cognitive agents:
1. **Meta Agent** - Orchestrator, activity classifier, performance reviewer
2. **Interest Agent** - User interest modeling and research triggering
3. **Research Agent** - Deep research with citation and knowledge graphs
4. **Opportunity Agent** - Synthesizes ideas and recommendations
5. **Brainstorming Agent** - Interactive sessions with KB + web search

## Setup

### Prerequisites

- Python 3.10+
- OpenRouter API key (free): https://openrouter.ai
- Docker (for Qdrant) or use pgvector alternative

### Installation

```bash
# Clone the repo
git clone <your-repo-url>
cd personal-assistant

# Install dependencies
pip install -e ".[dev]"

# Copy environment template
cp .env.example .env

# Edit .env and add your API keys
# OPENROUTER_API_KEY=sk-or-v1-...
# GITHUB_TOKEN=github_pat_...
```

### Configuration

Edit `config/settings.toml`:

```toml
[models]
meta = "google/gemma-3b-european-union:free"
reasoning = "google/gemma-3b-european-union:free"
embedding = "nomic-embed-text"

[runtime]
openrouter_api_key = "${OPENROUTER_API_KEY}"
max_concurrent_requests = 3
```

### Start Services

```bash
# Start Qdrant (vector DB)
docker compose up -d

# Or use pgvector instead (see docker-compose.yml)
```

### Run

```bash
# CLI
pa ask "What am I interested in?"
pa interests
pa brainstorm

# Or run the engine directly
python -m src.adapters.cli.app
```

## Documentation

- [Architecture & Plans](docs/personal-assistant.plans.md)
- [Implementation Roadmap](docs/personal-assistant.implementation.md)
- [Agent Architecture Guide](docs/agent.architecture-guide.md)
- [OpenRouter Runtime](docs/impl/07-openrouter-llm-runtime.md)

## Project Structure

```
personal-assistant/
├── pyproject.toml
├── config/
│   ├── settings.toml
│   └── topics.toml
├── src/
│   ├── core/           # Core Engine
│   ├── agents/         # 5 cognitive agents
│   ├── skills/         # Shared skills library
│   ├── ingest/         # Activity sensing pipeline
│   ├── research/       # Research connectors
│   ├── store/          # Storage layer
│   ├── llm/            # OpenRouter runtime
│   └── adapters/       # CLI & Slack interfaces
├── skills/             # Orchestration skill templates
└── tests/
```

## License

MIT
