---
title: "Telegram Mini App Implementation: Comprehensive Setup Guide"
created: 2026-06-23
updated: 2026-06-23
version: 1.0.0
status: Draft
tags:
  - how-to
  - architecture
  - telegram
changelog:
  - version: 1.0.0
    date: 2026-06-23
    changes: "Initial implementation guide: repo structure decision, daemon integration, dev workflows, shared state concurrency, testing strategy, and deployment roadmap."
audience: "Backend and frontend developers implementing the Telegram Mini App gateway; DevOps for deployment configuration"
related:
  - docs/telegram-gateway.rfc.mini-app-architecture.md
  - docs/DAEMON.md
  - docs/impl/01-cli-and-core-engine.md
  - docs/brainstorming-agent.profile-and-plan.md
reference:
  - https://core.telegram.org/bots/webapps
  - https://core.telegram.org/bots/api
---

# Telegram Mini App Implementation: Comprehensive Setup Guide

This guide complements the RFC ([telegram-gateway.rfc.mini-app-architecture.md](telegram-gateway.rfc.mini-app-architecture.md)) with detailed implementation decisions, architecture, and workflows for building the Telegram Mini App gateway.

## Overview

This document answers the six critical implementation questions that the RFC introduced but did not detail:

1. **Repository structure** — Monorepo vs multi-repo
2. **Daemon integration** — How the background daemon coexists with the API server
3. **Shared state & concurrency** — Preventing race conditions on `knowledge.db`
4. **Development workflow** — Step-by-step local setup and iteration
5. **Deployment strategy** — Docker, environment config, and production hosting
6. **Testing strategy** — Unit, integration, and end-to-end test organization

## Part 1: Repository Structure Decision

### Decision: Monorepo with `backend/` and `frontend/` Directories

**Recommendation: Single `personal-assistant/` repository with top-level `backend/` and `frontend/` directories.**

This is a **monorepo** structure, but with clear separation of concerns.

### Rationale

| Factor | Monorepo | Multi-Repo |
|--------|----------|-----------|
| **Type sharing** | Single source of truth for Commands/Events | API schema or manual sync; drift risk |
| **Development speed** | One `git clone`, one install sequence | Clone two repos; install twice; git sync friction |
| **Versioning** | Synchronized backend + frontend releases | Independent versions; coordination burden |
| **CI/CD** | Single pipeline with conditional jobs | Two pipelines; mirror configs |
| **Deployment** | Single container image (backend + frontend bundled) | Two images; orchestration complexity |
| **Shared infrastructure** | Docker Compose for local dev (one file) | Docker Compose with two service definitions |

**Decision justification:**
- Personal Assistant is a **single product with unified branding and experience**; not a platform with independent consumers
- Type sharing (Commands/Events) is **load-bearing** for correctness; monorepo prevents drift
- The team is small; coordination overhead is minimal
- Both backend and frontend are developed and deployed together every sprint

### Multi-Repo Alternative (Not Recommended)

If the frontend needs independent releases or a separate team manages it, keep `personal-assistant-backend` and `personal-assistant-miniapp-frontend` as separate repositories. Link them in CI/CD via dependency pinning (e.g., `backend` pins a specific `frontend` release tag).

**For now:** Use monorepo. Refactor to multi-repo later if needs change.

---

## Part 2: Recommended Directory Structure

### Comprehensive Tree

```
personal-assistant/
│
├── .gitignore
├── .env.example                     # Shared env template (bot token, API key, etc.)
├── .env                             # (user-created, not committed)
├── .github/
│   └── workflows/
│       ├── backend-tests.yml        # Backend pytest + lint
│       ├── frontend-tests.yml       # Frontend jest/vitest + lint
│       └── deploy.yml               # Build + deploy to Fly.io
│
├── backend/                         # Python FastAPI + aiogram backend
│   ├── src/
│   │   ├── __init__.py
│   │   ├── core/                    # (existing: engine, commands, events, bus, signals)
│   │   │   ├── engine.py
│   │   │   ├── commands.py
│   │   │   ├── events.py
│   │   │   ├── bus.py
│   │   │   ├── jobs.py
│   │   │   ├── signals.py
│   │   │   └── __init__.py
│   │   │
│   │   ├── adapters/                # User-facing gateways
│   │   │   ├── __init__.py
│   │   │   ├── cli/                 # (existing: CLI interface)
│   │   │   │   └── app.py
│   │   │   │
│   │   │   └── telegram/            # NEW: Telegram bot + API
│   │   │       ├── __init__.py
│   │   │       ├── app.py           # Main entry: unified bot + API app
│   │   │       ├── config.py        # Telegram config + settings loading
│   │   │       ├── auth.py          # Mini App initData validation
│   │   │       ├── api.py           # FastAPI router + endpoints
│   │   │       ├── bot_handler.py   # aiogram handlers (/ask, /brainstorm, etc.)
│   │   │       ├── renderers.py     # Event → Telegram message formatting
│   │   │       ├── models.py        # Pydantic request/response models
│   │   │       ├── websocket.py     # WebSocket connection management
│   │   │       ├── graph.py         # Graph fetch endpoint
│   │   │       ├── digest.py        # Digest formatting + posting
│   │   │       ├── notifications.py # Event-triggered alerts
│   │   │       └── tests/           # Telegram-specific tests
│   │   │           ├── test_auth.py
│   │   │           ├── test_api.py
│   │   │           ├── test_bot.py
│   │   │           └── test_graph.py
│   │   │
│   │   ├── agents/                  # (existing: Interest, Research, Brainstorm, etc.)
│   │   │   ├── interest/
│   │   │   ├── research/
│   │   │   ├── brainstorm/
│   │   │   └── ...
│   │   │
│   │   ├── daemon/                  # (existing: signal ingest loop)
│   │   │   ├── service.py
│   │   │   ├── manager.py
│   │   │   ├── connector_base.py
│   │   │   ├── connectors/
│   │   │   └── __init__.py
│   │   │
│   │   ├── store/                   # (existing: knowledge.db, vector DB)
│   │   │   ├── knowledge.py
│   │   │   ├── vector.py
│   │   │   ├── memory.py
│   │   │   └── __init__.py
│   │   │
│   │   ├── llm/                     # (existing: OpenRouter wrapper)
│   │   │   └── openrouter.py
│   │   │
│   │   ├── skills/                  # Shared skill library
│   │   │   └── ...
│   │   │
│   │   └── main_engine.py           # PersonalAssistantEngine public API
│   │
│   ├── tests/
│   │   ├── conftest.py              # Pytest fixtures (temp DB, fake LLM, etc.)
│   │   ├── test_signal_flow.py      # (existing integration tests)
│   │   ├── test_telegram_api.py     # NEW: API integration tests
│   │   ├── test_telegram_bot.py     # NEW: Bot handler tests
│   │   └── test_daemon_with_api.py  # NEW: Daemon + API coexistence tests
│   │
│   ├── Dockerfile                   # Backend container image
│   ├── pyproject.toml              # Poetry config; pip dependencies
│   ├── poetry.lock
│   ├── .dockerignore
│   └── README.md                    # Backend-specific setup / command reference
│
├── frontend/                        # TypeScript React Mini App
│   ├── public/
│   │   ├── index.html               # Single entry point
│   │   ├── favicon.ico
│   │   └── manifest.json            # PWA manifest
│   │
│   ├── src/
│   │   ├── main.tsx                 # Entry point; Telegram SDK init
│   │   ├── app.tsx                  # Main app router + layout
│   │   │
│   │   ├── types/
│   │   │   ├── commands.ts          # Command types (mirror backend)
│   │   │   ├── events.ts            # Event types (mirror backend)
│   │   │   ├── api.ts               # API request/response types
│   │   │   └── index.ts             # Public exports
│   │   │
│   │   ├── api/
│   │   │   ├── client.ts            # HTTP + WebSocket client
│   │   │   ├── auth.ts              # Extract initData from Telegram
│   │   │   └── constants.ts         # API base URL, timeouts
│   │   │
│   │   ├── hooks/
│   │   │   ├── useJob.ts            # Subscribe to job events via WebSocket
│   │   │   ├── useInterests.ts      # Fetch + manage interests
│   │   │   ├── useBrainstorm.ts     # Multi-turn session state
│   │   │   ├── useTelegram.ts       # Telegram WebApp SDK integration
│   │   │   └── useAuth.ts           # Mini App auth status
│   │   │
│   │   ├── components/
│   │   │   ├── Chat/
│   │   │   │   ├── ChatView.tsx     # Message list + input
│   │   │   │   ├── Message.tsx      # Single message with citations
│   │   │   │   ├── Citations.tsx    # Citation block (expandable)
│   │   │   │   └── ChatInput.tsx    # Input field + send button
│   │   │   │
│   │   │   ├── Brainstorm/
│   │   │   │   ├── BrainstormView.tsx # Multi-turn thread view
│   │   │   │   ├── Turn.tsx         # Single inquiry + ideation
│   │   │   │   ├── Proposals.tsx    # Ideation proposals + Save/Dismiss
│   │   │   │   └── TurnInput.tsx    # Input for next inquiry turn
│   │   │   │
│   │   │   ├── Graph/
│   │   │   │   ├── ResearchGraph.tsx # Cytoscape wrapper
│   │   │   │   ├── GraphControls.tsx # Search, zoom, layout
│   │   │   │   └── NodeDetails.tsx  # Node detail panel
│   │   │   │
│   │   │   ├── Interests/
│   │   │   │   ├── InterestsList.tsx # Interest cards list
│   │   │   │   ├── InterestCard.tsx # Single interest card
│   │   │   │   ├── TimelineFilter.tsx # 7d/30d/all time slider
│   │   │   │   └── AddInterest.tsx  # Add topic form
│   │   │   │
│   │   │   ├── Settings/
│   │   │   │   ├── SettingsView.tsx # Tab router
│   │   │   │   ├── ConnectorSettings.tsx # Toggle connectors
│   │   │   │   ├── TopicSettings.tsx # Manage tracked topics
│   │   │   │   ├── SourceSettings.tsx # Research depth, etc.
│   │   │   │   └── AccountSettings.tsx # User info, logout
│   │   │   │
│   │   │   └── Layout/
│   │   │       ├── Header.tsx       # Top bar + title
│   │   │       ├── TabBar.tsx       # Bottom tab navigation
│   │   │       ├── ErrorBoundary.tsx # Error fallback
│   │   │       └── LoadingSpinner.tsx # Universal spinner
│   │   │
│   │   ├── pages/
│   │   │   ├── Ask.tsx              # /ask route
│   │   │   ├── Brainstorm.tsx       # /brainstorm route
│   │   │   ├── Graph.tsx            # /graph route
│   │   │   ├── Interests.tsx        # /interests route
│   │   │   ├── Settings.tsx         # /settings route
│   │   │   └── NotFound.tsx         # 404
│   │   │
│   │   ├── stores/
│   │   │   ├── brainstormStore.ts   # Zustand: session state + turn history
│   │   │   ├── settingsStore.ts     # Zustand: user preferences
│   │   │   └── authStore.ts         # Zustand: auth status + user ID
│   │   │
│   │   ├── utils/
│   │   │   ├── formatting.ts        # Text/date formatting
│   │   │   ├── errors.ts            # Error handling, retry logic
│   │   │   └── validators.ts        # Input validation
│   │   │
│   │   ├── styles/
│   │   │   ├── tailwind.css         # Tailwind imports
│   │   │   ├── globals.css          # App-wide overrides
│   │   │   └── theme.css            # Dark mode, Telegram colors
│   │   │
│   │   └── index.css                # Root styles
│   │
│   ├── tests/
│   │   ├── setup.ts                 # Vitest setup
│   │   ├── components/
│   │   │   └── ChatView.test.tsx
│   │   ├── hooks/
│   │   │   └── useJob.test.ts
│   │   ├── api/
│   │   │   └── client.test.ts
│   │   └── e2e/
│   │       └── brainstorm.e2e.ts    # Playwright e2e tests
│   │
│   ├── vite.config.ts
│   ├── vitest.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── package.json
│   ├── .eslintrc.cjs
│   ├── .prettierrc
│   └── README.md                    # Frontend-specific setup / commands
│
├── docker-compose.yml               # Local dev: backend + frontend + optional Qdrant
├── Dockerfile                       # Multi-stage: build frontend, package backend
│
├── docs/
│   ├── telegram-gateway.rfc.mini-app-architecture.md
│   ├── telegram-gateway.implementation.comprehensive-setup.md (this file)
│   ├── DAEMON.md
│   ├── DEV_SETUP.md
│   ├── CONNECTORS.md
│   └── ...
│
├── config/
│   ├── settings.toml                # Daemon, LLM, storage, connectors config
│   └── .env.production              # Production env (Fly.io secrets)
│
├── scripts/
│   ├── dev.sh                       # Start backend + frontend locally
│   ├── deploy.sh                    # Deploy to Fly.io
│   ├── migrate-db.sh                # Run database migrations
│   └── seed-dev.sh                  # Populate test data
│
├── data/                            # Runtime data (gitignored)
│   ├── knowledge.db                 # SQLite database (shared by daemon + API)
│   ├── daemon.log                   # Daemon activity log
│   └── .gitkeep
│
├── README.md                        # Project root; quick start
├── CLAUDE.md                        # (existing: project instructions)
├── Makefile                         # Common tasks (dev, test, lint, deploy)
└── pyproject.toml                   # (backend) OR moved into backend/pyproject.toml
    (if moved, remove from root)
```

### Key Decisions Explained

#### 1. **Backend lives in `backend/`, frontend in `frontend/`**

Clear separation at the top level. Each has its own:
- Package manager (Poetry vs npm)
- Test runner (pytest vs vitest)
- Build process (no build for backend; Vite for frontend)
- CI/CD triggers (different linters, different test suites)

#### 2. **Telegram adapter is in `src/adapters/telegram/`**

Mirrors the existing CLI adapter structure. Easy to add a Slack adapter later in `src/adapters/slack/` if needed.

#### 3. **Frontend mirrors backend types in `frontend/src/types/`**

Commands and Events are defined in both places:
- **Backend:** `backend/src/core/commands.py` and `backend/src/core/events.py`
- **Frontend:** `frontend/src/types/commands.ts` and `frontend/src/types/events.ts`

These are **manually synced** (or auto-generated via a script). See [Type Sharing](#part-6-type-sharing-between-backend--frontend) for details.

#### 4. **Shared infrastructure in root: `docker-compose.yml`, `.env.example`**

Both backend and frontend are configured via a single `.env` file. Makes local dev setup simple.

#### 5. **Tests colocate with code**

- `backend/src/adapters/telegram/tests/` — Telegram-specific unit tests
- `backend/tests/test_telegram_api.py` — API integration tests
- `frontend/tests/components/` — Component tests
- `frontend/tests/e2e/` — End-to-end with Playwright

---

## Part 3: Daemon Integration & Shared State Architecture

### Context: The Existing Daemon

The daemon (in `src/daemon/service.py`) is a **background process** that:

1. Starts in its own process (via `pa daemon start`)
2. Creates a `PersonalAssistantEngine` instance
3. Runs periodic signal ingest cycles (every 15 minutes by default)
4. Fetches GitHub/browser/Slack activity
5. Passes signals to the Interest Agent
6. Publishes `ResearchTopic` commands when interest strength crosses threshold
7. Accesses `knowledge.db` to store interest state

### Problem: Both Daemon and API Need Access to the Engine

For the Mini App to work:
- The **API server** needs to handle commands (Ask, Brainstorm, Research) → call `engine.submit(cmd)`
- The **daemon** needs to ingest signals → call `engine.process_activity_signals()`
- Both need to access the same `knowledge.db` (SQLite)

### Architecture Decision: Unified Service with Internal Separation

**Recommendation: Single service process with daemon and API running as concurrent tasks within the same Python process, sharing one `PersonalAssistantEngine` instance and one `knowledge.db` file.**

```
┌─────────────────────────────────────────────────────────────┐
│ Backend Service Process (Docker container)                  │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ async def main():                                    │   │
│  │   # Shared engine (singleton)                        │   │
│  │   engine = PersonalAssistantEngine()                 │   │
│  │   await engine.initialize()                          │   │
│  │                                                      │   │
│  │   # Task 1: Bot handler + Web API                    │   │
│  │   api_task = asyncio.create_task(                    │   │
│  │       run_api_server(engine, host, port)             │   │
│  │   )                                                  │   │
│  │                                                      │   │
│  │   # Task 2: Daemon loop (background signal ingest)   │   │
│  │   daemon_task = asyncio.create_task(                 │   │
│  │       run_daemon_loop(engine, check_interval_sec)    │   │
│  │   )                                                  │   │
│  │                                                      │   │
│  │   # Wait for both (or any to fail)                   │   │
│  │   await asyncio.gather(api_task, daemon_task)        │   │
│  │                                                      │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  Shared State:                                               │
│  ├─ PersonalAssistantEngine (in-memory, one instance)       │
│  ├─ knowledge.db (SQLite file on disk)                      │
│  ├─ EventBus (shared pub-sub for streaming events)          │
│  └─ Qdrant connection pool (vector DB)                      │
│                                                              │
│  Processes:                                                  │
│  ├─ Telegram Bot Handler (aiogram long-poll)                │
│  ├─ FastAPI Web Server (REST + WebSocket)                   │
│  ├─ Daemon Loop (periodic signal ingest)                    │
│  └─ Optional: Health checks, graceful shutdown              │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Why This Architecture

| Aspect | Unified Service | Separate Services |
|--------|-----------------|-------------------|
| **Shared engine** | ✅ Same instance; no IPC | ❌ IPC overhead, state sync complexity |
| **SQLite** | ✅ Single connection pool; no locking | ❌ SQLite write locks; one writer at a time |
| **EventBus** | ✅ In-memory pub-sub; immediate | ❌ Network-based; latency |
| **Deployment** | ✅ Single container; simple | ❌ Two containers; orchestration |
| **Dev setup** | ✅ One command: `poetry run python -m src.adapters.telegram.app` | ❌ Two terminals; manual startup |
| **Operational complexity** | ✅ One process to monitor | ❌ Two processes; coordination |

**Tradeoff:** If either the daemon or API crashes, the whole service is down. Mitigation: implement health checks and graceful restart logic in the container orchestrator (Docker, Kubernetes).

### Implementing Unified Service

#### Step 1: Refactor daemon startup to be async-composable

**Before (existing):**
```python
# src/daemon/service.py
class PersonalAssistantDaemon:
    def __init__(self, engine):
        self.engine = engine
    
    async def run(self):
        while True:
            await self.ingest_signals()
            await asyncio.sleep(self.check_interval)
```

**After (async-friendly):**
```python
# src/daemon/service.py
class PersonalAssistantDaemon:
    def __init__(self, engine):
        self.engine = engine
        self._running = False
    
    async def run(self):
        """Run the daemon loop; call via asyncio.create_task()."""
        self._running = True
        try:
            while self._running:
                await self.ingest_signals()
                await asyncio.sleep(self.check_interval)
        except asyncio.CancelledError:
            logger.info("Daemon stopping gracefully")
            self._running = False
            raise
    
    def stop(self):
        """Signal the daemon to stop."""
        self._running = False
```

#### Step 2: Create a unified app entrypoint

**New file: `src/adapters/telegram/app.py`**

```python
# src/adapters/telegram/app.py
import asyncio
import logging
from typing import Coroutine

from src.main_engine import PersonalAssistantEngine
from src.daemon.service import PersonalAssistantDaemon
from src.adapters.telegram.api import create_api_app  # FastAPI app
from src.adapters.telegram.bot_handler import create_dispatcher
from src.adapters.telegram.config import load_telegram_config

logger = logging.getLogger(__name__)

async def run_bot_and_api(
    engine: PersonalAssistantEngine,
    bot_token: str,
    api_host: str = "0.0.0.0",
    api_port: int = 8000,
    check_interval_sec: int = 60,
) -> None:
    """
    Run bot handler + Web API + daemon loop in unified process.
    
    Both share the same engine instance and knowledge.db file.
    Graceful shutdown: SIGTERM stops all tasks.
    """
    
    # Initialize engine (load models, connect to DBs)
    await engine.initialize()
    logger.info("Engine initialized")
    
    # Create daemon
    daemon = PersonalAssistantDaemon(
        engine=engine,
        check_interval=check_interval_sec
    )
    
    # Create FastAPI app
    api_app = create_api_app(engine)
    
    # Create aiogram dispatcher
    dp = create_dispatcher(engine)
    bot = Bot(token=bot_token)
    
    # Tasks to run concurrently
    tasks: list[Coroutine] = [
        # Task 1: Daemon loop (background signal ingest)
        daemon.run(),
        
        # Task 2: FastAPI server
        uvicorn.run(
            api_app,
            host=api_host,
            port=api_port,
            log_level="info",
            access_log=True,
        ),
        
        # Task 3: Bot long-polling
        dp.start_polling(bot),
    ]
    
    logger.info("Starting unified service (daemon + API + bot)...")
    
    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        logger.info("Received SIGTERM; shutting down gracefully")
        daemon.stop()
        # FastAPI and bot will stop via event loop cleanup
    except Exception as e:
        logger.error(f"Service error: {e}")
        raise
    finally:
        await engine.shutdown()
        logger.info("Service shut down complete")

async def main():
    """Entry point: load config and start unified service."""
    config = load_telegram_config()
    
    engine = PersonalAssistantEngine()
    
    await run_bot_and_api(
        engine=engine,
        bot_token=config.telegram_bot_token,
        api_host=config.api_host,
        api_port=config.api_port,
        check_interval_sec=config.daemon_check_interval_sec,
    )

if __name__ == "__main__":
    asyncio.run(main())
```

#### Step 3: Manage SQLite Write Concurrency

SQLite has a **single-writer limitation**: only one process can hold an exclusive lock at a time. Since both the daemon and API write to `knowledge.db`, we need to handle this gracefully.

**Solution: Connection Pooling + Transaction Isolation**

```python
# src/store/knowledge.py (modified)
import aiosqlite
from contextlib import asynccontextmanager

class UnifiedKnowledgeStore:
    """
    Wrapper around SQLite with connection pooling and transaction management.
    Supports concurrent access from daemon + API via SERIALIZABLE isolation.
    """
    
    def __init__(self, db_path: str, pool_size: int = 5):
        self.db_path = db_path
        self.pool_size = pool_size
        self._pool: list[aiosqlite.Connection] = []
        self._available = asyncio.Queue()
    
    async def initialize(self):
        """Create connection pool."""
        for _ in range(self.pool_size):
            conn = await aiosqlite.connect(
                self.db_path,
                isolation_level="SERIALIZABLE",  # Strongest isolation
                timeout=30.0,  # 30-second lock timeout (raise TimeoutError if exceeded)
            )
            # Enable WAL mode for better concurrency
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.commit()
            self._pool.append(conn)
            self._available.put_nowait(conn)
    
    @asynccontextmanager
    async def get_connection(self):
        """Acquire a connection from the pool."""
        conn = await self._available.get()
        try:
            yield conn
        finally:
            self._available.put_nowait(conn)
    
    async def write_interest_signal(self, user_id: str, signal: ActivitySignal) -> None:
        """Example: daemon writes interest signals."""
        async with self.get_connection() as conn:
            try:
                await conn.execute("""
                    INSERT INTO interest_signals (user_id, topic, confidence, timestamp)
                    VALUES (?, ?, ?, ?)
                """, (user_id, signal.topic, signal.confidence, signal.timestamp))
                await conn.commit()
            except aiosqlite.OperationalError as e:
                if "database is locked" in str(e):
                    logger.warning(f"DB locked (write), retrying... {e}")
                    await asyncio.sleep(0.5)
                    return await self.write_interest_signal(user_id, signal)
                raise
    
    async def read_interests(self, user_id: str) -> list[dict]:
        """Example: API reads interests."""
        async with self.get_connection() as conn:
            cursor = await conn.execute("""
                SELECT topic, strength, last_active
                FROM interest_nodes
                WHERE user_id = ?
                ORDER BY strength DESC
            """, (user_id,))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def close_all(self):
        """Close all connections in pool."""
        for conn in self._pool:
            await conn.close()
```

**Key tactics:**

1. **WAL mode** (`PRAGMA journal_mode=WAL`) — Write-Ahead Logging allows readers and writers to coexist
2. **SERIALIZABLE isolation** — Prevents phantom reads and ensures consistency
3. **Connection pooling** — Multiple connections allow concurrent reads
4. **Retry logic** — If a write blocks, retry with backoff
5. **30-second timeout** — Prevent indefinite locking; fail fast

**Important:** The daemon's signal ingest is **low-frequency** (every 15 minutes by default), and the API's writes (user feedback, interest changes) are **user-initiated**. Conflicts should be rare in practice.

### Startup Sequence

```
1. Load config (telegram bot token, API port, daemon check interval)
2. Create PersonalAssistantEngine instance
3. engine.initialize()
   ├─ Load LLM (OpenRouter)
   ├─ Connect to SQLite (knowledge.db)
   ├─ Connect to Qdrant (vector DB)
   └─ Initialize all agents
4. Create daemon, FastAPI app, aiogram dispatcher
5. asyncio.gather(daemon.run(), api_server, bot.start_polling())
6. Wait for SIGTERM or fatal error
7. Gracefully shut down all tasks
```

**Time to ready:** ~3–5 seconds (LLM model loading dominates)

### Graceful Shutdown

When the container receives SIGTERM (e.g., during redeployment):

1. Stop accepting new requests (API returns 503)
2. Wait for in-flight requests to finish (timeout: 30 seconds)
3. Stop the daemon loop
4. Close all DB connections
5. Exit with code 0

```python
# In unified app.py
import signal

def setup_signal_handlers(daemon):
    """Register SIGTERM handler for graceful shutdown."""
    def handle_sigterm(signum, frame):
        logger.info("SIGTERM received; initiating graceful shutdown")
        daemon.stop()
        asyncio.get_event_loop().stop()
    
    signal.signal(signal.SIGTERM, handle_sigterm)
```

---

## Part 4: Development Workflow

### Prerequisites

- **Python 3.11+** with Poetry
- **Node.js 18+** with npm/yarn
- **Docker** (for running Qdrant locally, optional)
- **Telegram Bot** (created via @BotFather; token in .env)
- **OpenRouter API key** (for LLM calls)
- **GitHub token** (for activity connectors, optional for dev)

### Step-by-Step Local Setup

#### 1. Clone and Configure Environment

```bash
git clone https://github.com/diazoangga/personal-assistant.git
cd personal-assistant

# Copy environment template
cp .env.example .env

# Edit .env with your secrets
# Required:
#   TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklmnoPQRstuvwXYZ...
#   OPENROUTER_API_KEY=sk-or-v1-...
#   OPENROUTER_MODEL=meta-llama/llama-2-7b-chat  # or similar
# Optional:
#   GITHUB_TOKEN=ghp_...
#   SLACK_BOT_TOKEN=xoxb-...
```

#### 2. Backend Setup

```bash
cd backend

# Install Python dependencies
poetry install

# Activate environment (if not using 'poetry run')
poetry shell

# Run database migrations (first time only)
poetry run python scripts/migrate-db.py

# Verify setup
poetry run pytest tests/ -v
```

#### 3. Frontend Setup

```bash
cd ../frontend

# Install JavaScript dependencies
npm install

# Verify build
npm run build
```

#### 4. Start Services (Local Development)

**Option A: Unified service (recommended)**

```bash
# Terminal 1: Start backend (bot + API + daemon)
cd backend
poetry run python -m src.adapters.telegram.app
# Logs show:
#   INFO     Engine initialized
#   INFO     Starting unified service (daemon + API + bot)...
#   INFO     Bot long-polling started
#   INFO     Uvicorn running on http://0.0.0.0:8000
```

**Option B: Using docker-compose (advanced)**

```bash
# Terminal 1: All services in Docker
docker-compose -f docker-compose.yml up

# Includes: backend, frontend dev server, optional Qdrant
```

**Option C: Split terminals (manual)**

```bash
# Terminal 1: Backend API + bot (no daemon)
cd backend
poetry run python -m src.adapters.telegram.app --no-daemon

# Terminal 2: Frontend dev server
cd frontend
npm run dev

# Terminal 3: Daemon (optional; separate process for testing)
cd backend
poetry run python -m src.daemon.service
```

#### 5. Expose to HTTPS (for Telegram)

Telegram Mini Apps require HTTPS. For local development, use ngrok:

```bash
# Terminal 4: Create a secure tunnel
# (requires ngrok.com account; free tier available)
ngrok http 8000
# Output:
#   Forwarding                    https://abc123.ngrok.io -> http://localhost:8000

# Update .env
MINIAPP_URL=https://abc123.ngrok.io

# Update Telegram bot settings via @BotFather
# /setmenubutton -> https://abc123.ngrok.io
```

#### 6. Test the Flow

```bash
# Test the bot
curl -X POST https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage \
  -H "Content-Type: application/json" \
  -d '{"chat_id": "<YOUR_USER_ID>", "text": "Hi"}'

# Or use Telegram mobile/desktop and search for your bot
# Send: /ask what is rust programming?
# Expected: Bot responds with status, then streams answer

# Test the API
curl http://localhost:8000/api/v1/interests

# Test WebSocket
wscat -c "ws://localhost:8000/api/v1/stream/job-id-here?init_data=..."
```

#### 7. Development Iteration

**Make a backend change:**
```bash
# Edit src/adapters/telegram/bot_handler.py
# Backend auto-reloads via Uvicorn
# Check logs for changes
```

**Make a frontend change:**
```bash
# Edit frontend/src/components/Chat/ChatView.tsx
# Vite hot-reload applies change immediately (browser refresh)
# Open http://localhost:5173 in browser
```

**Run tests:**
```bash
# Backend tests (pytest)
cd backend
poetry run pytest tests/test_telegram_api.py -v

# Frontend tests (vitest)
cd frontend
npm run test:unit

# Both
npm run test:e2e  # End-to-end Playwright tests (requires backend running)
```

---

## Part 5: Docker & Deployment

### Docker Image Strategy: Multi-Stage Build

The production Docker image should:
1. Build the frontend (React → static bundle)
2. Copy static bundle into backend service
3. Serve the Mini App via FastAPI static files

**Dockerfile (production):**

```dockerfile
# Stage 1: Build frontend
FROM node:18-alpine AS frontend-builder
WORKDIR /build
COPY frontend/ .
RUN npm ci && npm run build

# Stage 2: Backend + bundled frontend
FROM python:3.11-slim
WORKDIR /app

# Install Poetry
RUN pip install poetry

# Copy backend
COPY backend/pyproject.toml backend/poetry.lock ./
RUN poetry install --no-dev

# Copy backend source
COPY backend/src ./src

# Copy frontend build output
COPY --from=frontend-builder /build/dist ./frontend_dist

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD poetry run python -c "import httpx; httpx.get('http://localhost:8000/health')"

# Run unified app
CMD ["poetry", "run", "python", "-m", "src.adapters.telegram.app"]
```

### Docker Compose for Local Development

**docker-compose.yml:**

```yaml
version: "3.8"

services:
  # Backend: bot + API + daemon
  backend:
    build:
      context: .
      dockerfile: backend/Dockerfile.dev
    container_name: pa-backend
    ports:
      - "8000:8000"
    volumes:
      - ./backend/src:/app/src
      - ./backend/tests:/app/tests
      - ./data:/app/data
    environment:
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
      - OPENROUTER_MODEL=${OPENROUTER_MODEL}
      - DATABASE_PATH=/app/data/knowledge.db
      - VECTOR_DB_HOST=qdrant
      - VECTOR_DB_PORT=6333
    depends_on:
      - qdrant
    command: poetry run python -m src.adapters.telegram.app

  # Frontend: Vite dev server
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile.dev
    container_name: pa-frontend
    ports:
      - "5173:5173"
    volumes:
      - ./frontend/src:/app/src
    environment:
      - VITE_API_URL=http://localhost:8000
    command: npm run dev

  # Vector DB (optional; stub out in tests if not using)
  qdrant:
    image: qdrant/qdrant:latest
    container_name: pa-qdrant
    ports:
      - "6333:6333"
    volumes:
      - ./data/qdrant:/qdrant/storage
    environment:
      - QDRANT_API_KEY=${QDRANT_API_KEY:-}

volumes:
  data:
    driver: local
```

**Start all services:**
```bash
docker-compose up -d
# All services ready at:
#   Backend: http://localhost:8000
#   Frontend: http://localhost:5173
#   Qdrant: http://localhost:6333
```

### Production Deployment: Fly.io

[Fly.io](https://fly.io) is a simple PaaS with automatic HTTPS, global deployment, and free tier availability.

#### 1. Setup Fly.io

```bash
# Install flyctl
curl -L https://fly.io/install.sh | sh

# Login
fly auth login

# Create a Fly.io app
fly launch --name personal-assistant

# This generates fly.toml and asks about database/regions
```

#### 2. Configure `fly.toml`

```toml
app = "personal-assistant"
primary_region = "sjc"  # San Jose, USA (or your preference)

[build]
builder = "docker"
dockerfile = "Dockerfile"

[env]
  ENVIRONMENT = "production"
  LOG_LEVEL = "INFO"

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = true

[[services]]
  protocol = "tcp"
  internal_port = 8000
  processes = ["app"]
  
  [[services.ports]]
    port = 443
    handlers = ["tls", "http"]
  
  [[services.ports]]
    port = 80
    handlers = ["http"]

[[vm]]
  cpu_kind = "shared"
  cpus = 2
  memory_mb = 512
```

#### 3. Set Secrets

```bash
# Set environment variables (secrets)
fly secrets set \
  TELEGRAM_BOT_TOKEN="1234567890:ABCdef..." \
  OPENROUTER_API_KEY="sk-or-v1-..." \
  OPENROUTER_MODEL="meta-llama/llama-2-7b-chat"

# Verify secrets are set
fly secrets list
```

#### 4. Deploy

```bash
# Deploy the app
fly deploy

# Monitor deployment
fly logs --follow

# Check status
fly status
```

**Result:** Your app is live at `https://personal-assistant.fly.dev` (or your custom domain).

### Monitoring & Observability

**Logging:**
```python
# backend/src/adapters/telegram/app.py
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,  # Log to stdout for container collection
)
```

**Health check endpoint:**
```python
# backend/src/adapters/telegram/api.py
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "daemon_running": daemon._running,
    }
```

**On Fly.io:**
```bash
# View logs
fly logs

# SSH into running machine (for debugging)
fly ssh console

# Monitor CPU/memory
fly status
```

---

## Part 6: Type Sharing Between Backend & Frontend

### Problem

Commands and Events are defined in Python but used in TypeScript. Keeping them in sync manually is error-prone.

### Solution: Single Source of Truth + Code Generation

**Approach: Use OpenAPI schema as the source of truth**

1. Backend defines all command/event types in Python Pydantic models
2. FastAPI generates OpenAPI (Swagger) schema automatically
3. Frontend generates TypeScript types from OpenAPI schema
4. CI/CD validates schema hasn't changed unexpectedly

#### Step 1: Define Backend Models (Python)

**backend/src/adapters/telegram/models.py:**

```python
from pydantic import BaseModel
from typing import Literal, Optional, List

# Request models (what the frontend sends)
class AskRequest(BaseModel):
    query: str
    session_id: Optional[str] = None

class BrainstormRequest(BaseModel):
    text: str
    session_id: str

class FeedbackRequest(BaseModel):
    ref: str
    verdict: Literal["accept", "reject"]
    note: Optional[str] = None

# Response models (what the backend sends)
class Citation(BaseModel):
    title: str
    url: str
    authors: Optional[List[str]] = None
    year: Optional[int] = None
    source: str  # "Semantic Scholar", "arXiv", etc.

class EventPayload(BaseModel):
    type: Literal["started", "progress", "message", "result", "error"]
    job_id: str
    timestamp: str
    
    # Type-specific fields (use Union for Pydantic v2)
    # ... or use discriminated unions

class InterestCard(BaseModel):
    topic: str
    strength: float
    last_active: str
    last_researched: Optional[str] = None
```

#### Step 2: Auto-Generate OpenAPI Schema

**backend/src/adapters/telegram/api.py:**

```python
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

app = FastAPI(
    title="Personal Assistant API",
    version="1.0.0",
    openapi_url="/api/v1/openapi.json",  # Expose schema
)

# FastAPI auto-generates schema from route signatures + Pydantic models
# Schema available at: GET /api/v1/openapi.json
```

#### Step 3: Generate TypeScript Types

**frontend/scripts/generate-types.ts:**

```typescript
import fetch from "node-fetch";
import { writeFileSync } from "fs";
import { resolve } from "path";
import openapiTS from "openapi-typescript";

async function generateTypes() {
  const backendUrl = process.env.BACKEND_URL || "http://localhost:8000";
  const schemaUrl = `${backendUrl}/api/v1/openapi.json`;

  console.log(`Fetching OpenAPI schema from ${schemaUrl}`);
  const response = await fetch(schemaUrl);
  const schema = await response.json();

  // Generate TypeScript types using openapi-typescript
  const types = await openapiTS(schema);

  // Write to frontend/src/types/api.generated.ts
  const outputPath = resolve(__dirname, "../src/types/api.generated.ts");
  writeFileSync(outputPath, types);
  console.log(`Generated ${outputPath}`);
}

generateTypes().catch(console.error);
```

**frontend/package.json:**

```json
{
  "scripts": {
    "generate-types": "ts-node scripts/generate-types.ts",
    "dev": "npm run generate-types && vite"
  }
}
```

#### Step 4: Use Generated Types in Frontend

**frontend/src/types/index.ts:**

```typescript
// Re-export generated types
export type * from "./api.generated";

// Import and use in components
import { components } from "./api.generated";
type InterestCard = components["schemas"]["InterestCard"];
```

#### Step 5: CI/CD: Validate Schema Stability

**In GitHub Actions:**

```yaml
name: Backend Compatibility
on: [pull_request]
jobs:
  schema:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Start backend
        run: docker-compose up -d backend
      
      - name: Generate types
        run: cd frontend && npm run generate-types
      
      - name: Check schema changed
        run: |
          if git diff --quiet frontend/src/types/api.generated.ts; then
            echo "✅ API schema unchanged"
          else
            echo "❌ API schema changed; update via: npm run generate-types"
            exit 1
          fi
```

### Alternative: Manual Sync (Simpler for Small Teams)

If you prefer simplicity and are okay with manual synchronization:

1. **Define types once in a shared TypeScript file** (frontend/src/types/commands.ts)
2. **Reference that file in your API docs** (via docstrings)
3. **Document the mapping** in the RFC/implementation guide
4. **CI/CD lint** checks that backend handlers match frontend expectations

This is less automated but works fine for a small team with tight communication.

---

## Part 7: Shared State & Concurrency Management

### SQLite Write Serialization

SQLite has a fundamental limitation: **only one writer at a time**. When the daemon and API both try to write concurrently, one must wait.

#### Conflict Scenarios

1. **Daemon writes interest signal** → API tries to update interest strength
   - Both need to access `interest_signals` and `interest_nodes` tables
   - Solution: Use SERIALIZABLE isolation + WAL mode (see Part 3)

2. **API stores feedback** → Daemon reads interest history
   - API: `INSERT INTO feedback_log`
   - Daemon: `SELECT * FROM interest_signals`
   - Solution: Readers don't block; only writers wait for each other

3. **API saves brainstorm session** → Daemon continues running
   - API: `INSERT INTO brainstorm_turns`
   - Daemon: No interference (separate table)
   - Solution: Table-level isolation (different lock scopes)

#### Implementation: Write Locking Pattern

```python
# src/store/knowledge.py
from asyncio import Lock

class UnifiedKnowledgeStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._write_lock = Lock()  # Serializes all writes
        self._conn: aiosqlite.Connection | None = None
    
    async def initialize(self):
        self._conn = await aiosqlite.connect(
            self.db_path,
            isolation_level="SERIALIZABLE",
            timeout=30.0,
        )
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.commit()
    
    async def write_interest_signal(self, signal):
        """Daemon: write interest signal."""
        async with self._write_lock:
            # Only one writer at a time; readers can proceed in parallel
            await self._conn.execute(
                "INSERT INTO interest_signals (topic, confidence, ts) VALUES (?, ?, ?)",
                (signal.topic, signal.confidence, signal.timestamp),
            )
            await self._conn.commit()
    
    async def read_interests(self):
        """API: read interests (no lock needed)."""
        cursor = await self._conn.execute(
            "SELECT topic, strength FROM interest_nodes ORDER BY strength DESC"
        )
        return await cursor.fetchall()
```

#### Retry Logic with Exponential Backoff

```python
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential

class UnifiedKnowledgeStore:
    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=0.5, min=0.1, max=10),
    )
    async def write_interest_signal(self, signal):
        """Retry if database is locked."""
        async with self._write_lock:
            try:
                await self._conn.execute(
                    "INSERT INTO interest_signals ...",
                    (signal.topic, ...),
                )
                await self._conn.commit()
            except aiosqlite.OperationalError as e:
                if "database is locked" in str(e):
                    logger.warning(f"DB locked; retrying...")
                    raise  # Trigger retry
                raise
```

#### WAL Mode Benefits

**Write-Ahead Logging (WAL)** improves concurrency:

```python
# Enable WAL on database initialization
await conn.execute("PRAGMA journal_mode=WAL")
await conn.commit()

# WAL mode benefits:
# - Readers don't block writers
# - Multiple concurrent readers
# - Writers still serialize (but faster checkpoints)
```

### EventBus: Shared In-Memory Pub-Sub

The EventBus is used for streaming results to connected clients. Both daemon and API publish events; WebSocket clients subscribe.

```python
# src/core/bus.py (existing, used by all)
class EventBus:
    def __init__(self):
        self._subscriptions: dict[str, list[asyncio.Queue]] = {}
    
    async def publish(self, event: Event):
        """Publish event to all subscribers."""
        if event.job_id in self._subscriptions:
            for queue in self._subscriptions[event.job_id]:
                queue.put_nowait(event)
    
    async def subscribe(self, job_id: str) -> AsyncIterator[Event]:
        """Subscribe to events for a job."""
        queue: asyncio.Queue = asyncio.Queue()
        if job_id not in self._subscriptions:
            self._subscriptions[job_id] = []
        self._subscriptions[job_id].append(queue)
        
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscriptions[job_id].remove(queue)
```

**Usage:**
```python
# Daemon publishes research trigger
await engine.submit(ResearchTopic(topic="rust", depth="normal"))

# API subscribes and streams to WebSocket
async for event in engine.events(job_id):
    await websocket.send_json(event.to_dict())
```

---

## Part 8: Testing Strategy

### Unit Tests (Backend)

**Location:** `backend/tests/test_telegram_*.py`

**Scope:** Fast, isolated, no external dependencies

```python
# backend/tests/test_telegram_auth.py
import pytest
from src.adapters.telegram.auth import validate_init_data

def test_validate_init_data_valid():
    """Valid signature passes."""
    bot_token = "123456:ABC-def1234567890abcdefghijklmnop"
    init_data = "hash=ABCD&user_id=123&auth_date=1234567890"
    result = validate_init_data(init_data, bot_token)
    assert result is not None
    assert result["user_id"] == 123

def test_validate_init_data_invalid_signature():
    """Invalid signature fails."""
    bot_token = "123456:ABC-def1234567890abcdefghijklmnop"
    init_data = "hash=WRONGHASH&user_id=123&auth_date=1234567890"
    result = validate_init_data(init_data, bot_token)
    assert result is None

def test_validate_init_data_expired():
    """Timestamp > 5 minutes old fails."""
    import time
    bot_token = "123456:ABC-def1234567890abcdefghijklmnop"
    old_timestamp = int(time.time()) - 600  # 10 minutes ago
    init_data = f"hash=VALIDHASH&auth_date={old_timestamp}"
    result = validate_init_data(init_data, bot_token)
    assert result is None
```

### Integration Tests (Backend + API)

**Location:** `backend/tests/test_telegram_api.py`

**Scope:** API endpoints + engine interaction; use in-memory stubs for LLM/storage

```python
# backend/tests/test_telegram_api.py
import pytest
from fastapi.testclient import TestClient
from src.adapters.telegram.api import create_api_app
from src.main_engine import PersonalAssistantEngine

@pytest.fixture
async def engine_with_stubs():
    """Create engine with fake LLM and temp DB."""
    engine = PersonalAssistantEngine()
    engine.llm = FakeLLM()  # Stub LLM
    engine.store = FakeKnowledgeStore()  # Stub storage
    await engine.initialize()
    yield engine
    await engine.close()

@pytest.fixture
def client(engine_with_stubs):
    """FastAPI test client."""
    app = create_api_app(engine_with_stubs)
    return TestClient(app)

def test_api_ask_endpoint(client):
    """POST /api/v1/ask submits command and returns job_id."""
    response = client.post("/api/v1/ask", json={"query": "what is rust?"})
    assert response.status_code == 200
    assert "job_id" in response.json()

def test_api_interests_endpoint(client):
    """GET /api/v1/interests returns interest list."""
    response = client.get("/api/v1/interests")
    assert response.status_code == 200
    assert "interests" in response.json()

@pytest.mark.asyncio
async def test_websocket_streaming(client):
    """WebSocket /api/v1/stream/{job_id} streams events."""
    # This requires async test client or pytest-asyncio
    with client.websocket_connect("/api/v1/stream/test-job-id") as ws:
        ws.send_json({"init_data": "..."})
        data = ws.receive_json()
        assert data["type"] in ["started", "progress", "message", "result"]
```

### Bot Handler Tests

**Location:** `backend/tests/test_telegram_bot.py`

**Scope:** Verify handlers call engine correctly; test event rendering

```python
# backend/tests/test_telegram_bot.py
import pytest
from unittest.mock import AsyncMock, patch
from aiogram import Dispatcher
from aiogram.types import Message, User, Chat

@pytest.fixture
async def dp_with_mock_engine():
    """Create dispatcher with mocked engine."""
    mock_engine = AsyncMock()
    dp = Dispatcher()
    # Register handlers (module must be importable)
    from src.adapters.telegram import bot_handler
    bot_handler.register_handlers(dp, mock_engine)
    yield dp, mock_engine

@pytest.mark.asyncio
async def test_handle_ask_command(dp_with_mock_engine):
    """Test /ask command submits Ask command."""
    dp, mock_engine = dp_with_mock_engine
    mock_engine.submit.return_value = "job-id-123"
    
    # Simulate incoming message
    user = User(id=123, is_bot=False, first_name="Test")
    chat = Chat(id=123, type="private")
    message = Message(
        message_id=1,
        from_user=user,
        chat=chat,
        text="/ask what is rust?",
        date=0,
    )
    
    # Call handler
    # (This is pseudo-code; actual aiogram testing is more complex)
    # await bot_handler.handle_ask(message)
    
    # Verify engine.submit was called
    # mock_engine.submit.assert_called_once()
```

### End-to-End Tests (Frontend + Backend)

**Location:** `frontend/tests/e2e/`

**Tools:** Playwright (headless browser automation)

**Scope:** Full user flows; real backend running

```typescript
// frontend/tests/e2e/brainstorm.e2e.ts
import { test, expect } from "@playwright/test";

test.describe("Brainstorm Flow", () => {
  test.beforeEach(async ({ page }) => {
    // Start Telegram Mini App locally
    await page.goto("http://localhost:5173");
  });

  test("Ask then brainstorm", async ({ page }) => {
    // Navigate to Ask tab
    await page.click('button:has-text("Ask")');

    // Type a query
    await page.fill('input[placeholder="What do you want to know?"]', "rust");
    await page.click('button:has-text("Send")');

    // Wait for response
    await page.waitForSelector("text=Here's what I found");

    // Navigate to Brainstorm tab
    await page.click('button:has-text("Brainstorm")');

    // Type an inquiry turn
    await page.fill('input[placeholder="Inquiry"]', "how do I use async?");
    await page.click('button:has-text("Send")');

    // Wait for ideation proposals
    await page.waitForSelector("text=Proposal:");

    // Save an idea
    await page.click('button:has-text("Save")');

    // Verify success message
    await expect(page.locator("text=Idea saved")).toBeVisible();
  });
});
```

**Run e2e tests:**
```bash
cd frontend

# Start backend first
cd ../backend && poetry run python -m src.adapters.telegram.app &

# Run tests
cd ../frontend
npm run test:e2e
```

### CI/CD Pipeline (GitHub Actions)

**.github/workflows/test.yml:**

```yaml
name: Tests
on: [push, pull_request]

jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: "3.11"
      
      - name: Install dependencies
        run: |
          cd backend
          pip install poetry
          poetry install
      
      - name: Lint (ruff)
        run: cd backend && poetry run ruff check src/
      
      - name: Type check (mypy)
        run: cd backend && poetry run mypy src/
      
      - name: Tests (pytest)
        run: cd backend && poetry run pytest tests/ -v
        env:
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY_TEST }}

  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Node
        uses: actions/setup-node@v3
        with:
          node-version: "18"
      
      - name: Install dependencies
        run: cd frontend && npm ci
      
      - name: Lint (eslint)
        run: cd frontend && npm run lint
      
      - name: Build
        run: cd frontend && npm run build
      
      - name: Tests (vitest)
        run: cd frontend && npm run test:unit
      
      - name: E2E tests (playwright)
        run: |
          cd backend && poetry run python -m src.adapters.telegram.app &
          cd ../frontend && npm run test:e2e

  integration:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Build Docker image
        run: docker build -t pa:test .
      
      - name: Start services
        run: docker-compose -f docker-compose.yml up -d
      
      - name: Health check
        run: |
          for i in {1..30}; do
            curl -f http://localhost:8000/health && exit 0
            sleep 2
          done
          exit 1
      
      - name: Smoke tests
        run: |
          curl -f http://localhost:8000/api/v1/interests
          curl -f http://localhost:5173
```

---

## Part 9: Database Migrations

Since both daemon and API write to `knowledge.db`, schema changes must be coordinated.

### Migration Pattern

Use **Alembic** (database migration tool for Python) to version schema changes.

#### 1. Setup Alembic

```bash
cd backend
poetry add alembic
alembic init migrations
```

#### 2. Create a Migration

```bash
# Create migration file (auto-generate from model changes)
alembic revision --autogenerate -m "Add brainstorm_turns table"

# Or manual migration
alembic revision -m "Add brainstorm_turns table"
```

**Example migration: migrations/versions/0001_add_brainstorm_turns.py**

```python
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "brainstorm_turns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("brainstorm_sessions.id")),
        sa.Column("role", sa.String(16)),  # "user" or "assistant"
        sa.Column("text", sa.Text()),
        sa.Column("timestamp", sa.DateTime()),
    )

def downgrade():
    op.drop_table("brainstorm_turns")
```

#### 3. Run Migrations on Startup

```python
# backend/src/store/knowledge.py
async def initialize(self):
    # Auto-run migrations before opening DB
    import subprocess
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    
    # Then open connection
    self._conn = await aiosqlite.connect(self.db_path)
```

#### 4. Lock Mechanism During Migration

If a migration is long-running, prevent daemon/API from accessing DB:

```python
class UnifiedKnowledgeStore:
    def __init__(self):
        self._migration_lock = Lock()
    
    async def initialize(self):
        async with self._migration_lock:
            # Run migrations with exclusive lock
            await self._run_migrations()
        # After migration, normal operation resumes
```

---

## Part 10: Logging & Debugging

### Logging Setup

```python
# backend/src/adapters/telegram/app.py
import logging
import sys

def setup_logging():
    # Root logger
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),  # To stdout (container logs)
            logging.FileHandler("data/app.log"),  # Also to file (for history)
        ],
    )
    
    # Silence noisy libraries
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)

if __name__ == "__main__":
    setup_logging()
    asyncio.run(main())
```

### Log Levels & Format

```
2026-06-23 10:15:45 [INFO] src.adapters.telegram.app: Engine initialized
2026-06-23 10:15:46 [INFO] src.adapters.telegram.app: Starting unified service (daemon + API + bot)...
2026-06-23 10:15:46 [INFO] src.adapters.telegram.api: Uvicorn running on http://0.0.0.0:8000
2026-06-23 10:15:50 [DEBUG] src.daemon.service: Ingesting signals from GitHub connector
2026-06-23 10:15:52 [DEBUG] src.agents.interest.agent: Classified 5 signals → topics: [rust, web3]
2026-06-23 10:15:53 [INFO] src.daemon.service: Research trigger: rust (strength=0.35)
2026-06-23 10:16:15 [DEBUG] src.adapters.telegram.bot_handler: Received /ask command: user_id=123
2026-06-23 10:16:15 [DEBUG] src.adapters.telegram.bot_handler: Submitted Ask command: job_id=abc123
```

### Frontend Logging

```typescript
// frontend/src/main.tsx
const isDev = import.meta.env.MODE === "development";

if (isDev) {
  // Enable console logging in dev
  window.DEBUG = true;
} else {
  // Send errors to Sentry in prod
  import("@sentry/react").then((Sentry) => {
    Sentry.init({
      dsn: import.meta.env.VITE_SENTRY_DSN,
      environment: import.meta.env.MODE,
    });
  });
}
```

### Debugging Commands

```bash
# View backend logs (live)
tail -f data/app.log

# View Docker logs
docker logs -f pa-backend

# View frontend console (browser DevTools)
# Or in Chromium headless mode
npm run test:e2e -- --debug

# SSH into running Fly.io machine
fly ssh console

# Check daemon status
curl http://localhost:8000/health
```

---

## Part 11: Security Considerations

### Telegram initData Validation

Every WebSocket connection and every Mini App API call must validate `initData`:

```python
# backend/src/adapters/telegram/auth.py
import hmac
import hashlib
import time
from urllib.parse import parse_qs

def validate_init_data(init_data: str, bot_token: str, max_age_sec: int = 300) -> dict | None:
    """
    Validate Telegram Mini App initData signature + timestamp.
    
    Args:
        init_data: URL-encoded string from Telegram (contains user, auth_date, hash)
        bot_token: Bot token (used as HMAC secret)
        max_age_sec: Max age of auth (default 5 minutes)
    
    Returns:
        Decoded user data if valid; None otherwise
    """
    try:
        # Parse query string
        data = parse_qs(init_data)
        signature = data.get("hash", [None])[0]
        auth_date = int(data.get("auth_date", [0])[0])
        
        # Check timestamp (prevent replay attacks)
        now = int(time.time())
        if now - auth_date > max_age_sec:
            return None
        
        # Build data_check_string (all fields except hash, sorted)
        pairs = sorted([f"{k}={v[0]}" for k, v in data.items() if k != "hash"])
        data_check_string = "\n".join(pairs)
        
        # Compute HMAC-SHA256
        secret_key = hashlib.sha256(bot_token.encode()).digest()
        computed_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        # Compare signatures (constant-time comparison)
        if not hmac.compare_digest(computed_hash, signature):
            return None
        
        # Extract user info
        import json
        user_data = json.loads(data.get("user", ["{}"]) [0])
        
        return {
            "user_id": user_data.get("id"),
            "username": user_data.get("username"),
            "first_name": user_data.get("first_name"),
            "auth_date": auth_date,
        }
    except Exception as e:
        logger.warning(f"Invalid initData: {e}")
        return None
```

### API Middleware: Validate on Every Request

```python
# backend/src/adapters/telegram/api.py
from fastapi import FastAPI, HTTPException, WebSocket, Query
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Skip auth for public endpoints
        if request.url.path in ["/health", "/openapi.json"]:
            return await call_next(request)
        
        # Require initData in headers or query params
        init_data = request.query_params.get("init_data") or request.headers.get("X-Init-Data")
        
        if not init_data:
            raise HTTPException(status_code=401, detail="Missing initData")
        
        user_data = validate_init_data(init_data, BOT_TOKEN)
        if not user_data:
            raise HTTPException(status_code=401, detail="Invalid initData")
        
        # Attach user data to request
        request.state.user_id = user_data["user_id"]
        request.state.user = user_data
        
        return await call_next(request)

app = FastAPI(
    middleware=[Middleware(AuthMiddleware)]
)
```

### Environment Secrets

Never commit secrets; use environment variables:

```bash
# .env (not committed)
TELEGRAM_BOT_TOKEN=1234567890:ABCdef...
OPENROUTER_API_KEY=sk-or-v1-...

# .env.example (committed; placeholder only)
TELEGRAM_BOT_TOKEN=your-bot-token-here
OPENROUTER_API_KEY=your-openrouter-key-here
```

### HTTPS Requirements

- **Development:** Use ngrok or similar tunnel
- **Production:** Fly.io auto-provides HTTPS
- **Rate limiting:** Add to FastAPI to prevent abuse

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app = FastAPI()
app.state.limiter = limiter

@app.post("/api/v1/ask")
@limiter.limit("10/minute")  # Max 10 asks per minute per IP
async def handle_ask(request: Request, ...):
    ...
```

---

## Part 12: Slack Gateway (Backlog)

**Status:** Slack adapter is in backlog as of this document's creation (2026-06-23).

**Existing reference:** [docs/impl/02-slack-gateway.md](docs/impl/02-slack-gateway.md) contains the complete Slack design and can be resurrected if needed.

### How to Keep Slack Code Maintainable While Backlog

Option A: **Delete Slack code entirely**
- Pros: Less maintenance burden; simpler codebase
- Cons: Must re-implement from scratch if Slack returns to priority
- Decision: Recommended if Slack is definitely deprioritized

Option B: **Keep Slack code; mark as disabled in config**
- Pros: Can re-enable quickly; code doesn't bitrot if referenced in docs
- Cons: Unused code in tree; temptation to accidentally activate
- Decision: Use if Slack might return within 6 months

**Recommendation:** **Option A (delete).** The RFC and implementation guide are sufficient to resurrect Slack. Keeping dead code creates confusion.

```bash
# If deleting Slack adapter
rm -rf backend/src/adapters/slack/
rm docs/impl/02-slack-gateway.md  # Move to archive or docs/backlog/
```

---

## Part 13: Troubleshooting Guide

### Common Issues & Solutions

#### Backend Won't Start

**Symptom:** `poetry run python -m src.adapters.telegram.app` exits immediately

**Causes & fixes:**
```bash
# 1. Missing environment variables
echo $TELEGRAM_BOT_TOKEN  # Should print your token
cp .env.example .env
# Edit .env with real values

# 2. Port conflict (8000 already in use)
lsof -i :8000  # See what's using port 8000
# Kill it or change API_PORT in .env

# 3. Poetry not found
poetry --version  # Should print version
pip install poetry  # Or install Poetry

# 4. Database locked (previous process didn't shut down)
rm data/knowledge.db  # Or wait 30 seconds for locks to release
```

#### API Won't Connect to Qdrant

**Symptom:** Logs show `ConnectionRefusedError: ... 6333`

**Fix:**
```bash
# Start Qdrant (if using docker-compose)
docker-compose up qdrant

# Or stub Qdrant in config (development only)
# config/settings.toml:
# [storage]
# vector_db_host = "localhost"
# vector_db_port = 6333  # Must be running or tests fail
```

#### Mini App Can't Reach Backend (CORS / Network)

**Symptom:** WebSocket connection fails; browser console shows CORS error

**Fix:**
```bash
# 1. Verify backend is running
curl http://localhost:8000/health  # Should return 200

# 2. Check ngrok tunnel is active
ngrok http 8000  # Should print: https://...ngrok.io

# 3. Update MINIAPP_URL in .env
MINIAPP_URL=https://...ngrok.io  # Not http://localhost

# 4. Frontend env variable points to backend
# frontend/.env.local:
VITE_API_URL=https://...ngrok.io/api/v1
```

#### Telegram Bot Doesn't Respond

**Symptom:** Send `/ask ...` in Telegram; no response for 5+ seconds

**Fix:**
```bash
# 1. Verify bot token is correct
echo $TELEGRAM_BOT_TOKEN

# 2. Check bot is running
curl -f http://localhost:8000/health

# 3. Check logs
tail -f data/app.log | grep "bot_handler"

# 4. Verify @BotFather registered the bot
# Go to @BotFather on Telegram; check /mybots list
```

#### Database Locked (Cannot Write)

**Symptom:** `aiosqlite.OperationalError: database is locked`

**Fix:**
```bash
# 1. Close all database connections (backend, tests, etc.)
pkill -f "python.*telegram.app"

# 2. Check for lingering locks
lsof data/knowledge.db

# 3. Enable WAL mode (better concurrency)
# Already done in UnifiedKnowledgeStore.initialize()

# 4. Increase timeout
# Retry logic with exponential backoff (see Part 7)
```

#### WebSocket Disconnects Unexpectedly

**Symptom:** Long-running /ask finishes but connection drops

**Fix:**
```typescript
// frontend/src/api/client.ts
const reconnect = async (job_id: string) => {
  let retries = 0;
  while (retries < 5) {
    try {
      return await new Promise((resolve, reject) => {
        const ws = new WebSocket(`...${job_id}`);
        ws.onopen = () => resolve(ws);
        ws.onerror = reject;
      });
    } catch (e) {
      retries++;
      await new Promise(r => setTimeout(r, 2 ** retries * 1000));  // Exponential backoff
    }
  }
  throw new Error("WebSocket reconnection failed");
};
```

#### Tests Fail with "Module not found"

**Symptom:** `ModuleNotFoundError: No module named 'src.adapters.telegram'`

**Fix:**
```bash
# 1. Run tests via Poetry (ensures PYTHONPATH is correct)
poetry run pytest tests/test_telegram_api.py -v
# NOT: python -m pytest

# 2. Check src/__init__.py exists
touch backend/src/__init__.py
touch backend/src/adapters/__init__.py
touch backend/src/adapters/telegram/__init__.py

# 3. Check working directory
pwd  # Should be .../personal-assistant/backend/
cd backend  # If not
```

---

## Part 14: Environment Configuration Reference

### Comprehensive `.env.example`

```bash
# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklmnoPQRstuvwXYZ_abcdefghijk
MINIAPP_URL=http://localhost:5173  # During dev; https://...ngrok.io for Telegram
MINIAPP_DOMAIN=localhost  # Used in Telegram bot settings

# LLM Configuration (OpenRouter)
OPENROUTER_API_KEY=sk-or-v1-xxxxx
OPENROUTER_MODEL=meta-llama/llama-2-7b-chat
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

# Activity Connectors (Optional)
GITHUB_TOKEN=ghp_xxxxx
SLACK_BOT_TOKEN=xoxb-xxxxx
SLACK_SIGNING_SECRET=xxx

# Database Configuration
DATABASE_PATH=./data/knowledge.db  # SQLite file path
VECTOR_DB_HOST=localhost           # Qdrant (vector DB)
VECTOR_DB_PORT=6333
QDRANT_API_KEY=                    # Optional if Qdrant requires auth

# API Server Configuration
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=4  # Number of Uvicorn worker processes

# Daemon Configuration
DAEMON_ENABLED=true
DAEMON_CHECK_INTERVAL_SEC=900      # 15 minutes
DAEMON_LOG_LEVEL=INFO

# Logging
LOG_LEVEL=INFO
LOG_FILE=./data/app.log

# Environment
ENVIRONMENT=development            # or "production" for Fly.io
DEBUG=false
```

### Production `.env` (Fly.io Secrets)

On Fly.io, secrets are set via `fly secrets set` and automatically available to the container:

```bash
fly secrets set \
  TELEGRAM_BOT_TOKEN="..." \
  OPENROUTER_API_KEY="..." \
  OPENROUTER_MODEL="meta-llama/llama-2-7b-chat" \
  DATABASE_PATH="/data/knowledge.db" \
  ENVIRONMENT="production" \
  API_PORT="8000"

# Verify
fly secrets list
```

---

## Summary Table: Key Decisions

| Question | Decision | Rationale |
|----------|----------|-----------|
| **Repo structure** | Monorepo (`backend/` + `frontend/`) | Single product; easy type sharing; unified CI/CD |
| **Daemon + API coexistence** | Unified service (single Python process) | Shared engine + in-memory EventBus; no IPC overhead |
| **Database concurrency** | Connection pooling + WAL + SERIALIZABLE isolation | SQLite single-writer; retry logic handles conflicts |
| **Type sharing** | OpenAPI schema → TypeScript codegen | Automated sync; single source of truth |
| **Frontend framework** | React 18 + Vite + TypeScript | Matches ecosystem; TailwindCSS for styling |
| **Graph visualization** | Cytoscape.js | Best performance for 50+ node graphs |
| **Bot library** | aiogram v3 | Async-first; composable; active maintenance |
| **Hosting (dev)** | ngrok tunnel to localhost:8000 | Fast iteration; real Telegram testing |
| **Hosting (prod)** | Fly.io | Auto HTTPS, global deploy, free tier available |
| **Testing framework** | pytest (backend) + vitest (frontend) + Playwright e2e | Industry standard; good integration |
| **Migrations** | Alembic (Python DB migration tool) | Versioned schema changes; rollback support |
| **Slack adapter** | Delete for now | Docs are sufficient for resurrection; simplify codebase |

---

## Next Steps

1. **Backend development**
   - Implement `src/adapters/telegram/app.py` (unified service)
   - Implement `src/adapters/telegram/api.py` (FastAPI endpoints)
   - Implement `src/adapters/telegram/bot_handler.py` (aiogram handlers)
   - Write unit + integration tests

2. **Frontend development**
   - Scaffold React app with Vite
   - Implement Chat, Brainstorm, Graph, Interests, Settings tabs
   - Integrate Telegram WebApp SDK for native features
   - Set up API client + WebSocket hook

3. **Infrastructure**
   - Set up Fly.io account
   - Create `Dockerfile` + `docker-compose.yml`
   - Configure CI/CD (GitHub Actions)
   - Set up monitoring + logging

4. **Testing & launch**
   - End-to-end tests with Playwright
   - Security review (auth, HTTPS, rate limiting)
   - Load testing (simulate 100+ concurrent users)
   - Launch on Fly.io; monitor for 48 hours

---

## Related Documents

- [telegram-gateway.rfc.mini-app-architecture.md](telegram-gateway.rfc.mini-app-architecture.md) — High-level RFC (this implementation guide assumes familiarity)
- [DAEMON.md](../DAEMON.md) — Daemon process documentation
- [impl/01-cli-and-core-engine.md](../impl/01-cli-and-core-engine.md) — Core engine and command/event contracts
- [brainstorming-agent.profile-and-plan.md](../brainstorming-agent.profile-and-plan.md) — Brainstorming agent (used by Mini App)
- [impl/06-research-agent.md](../impl/06-research-agent.md) — Research agent (supplies knowledge graphs)

---

## Document History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-06-23 | Initial comprehensive implementation guide covering repo structure, daemon integration, shared state concurrency, dev workflows, and testing strategy. |
