"""Unified Telegram Mini App backend service.

Runs three concurrent async tasks:
1. Daemon (signal ingest loop)
2. FastAPI server (REST + WebSocket API)
3. Telegram bot (long-polling)

All share the same PersonalAssistantEngine instance and knowledge.db.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from uvicorn import Server, Config

from ...daemon.service import PersonalAssistantDaemon
from ...main_engine import PersonalAssistantEngine
from .bot import TelegramBotHandler
from .handlers import router, set_dependencies

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Get config from environment
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MINI_APP_URL = os.getenv("MINI_APP_URL", "http://localhost:5173")  # Dev default
API_HOST = os.getenv("TELEGRAM_API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("TELEGRAM_API_PORT", "8000"))

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is required")


# Global task handles
_tasks: dict[str, asyncio.Task] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage app lifecycle: startup and shutdown."""
    logger.info("=" * 70)
    logger.info("Starting Unified Telegram Mini App Backend")
    logger.info("=" * 70)

    try:
        # Initialize engine (shared by daemon, API, and bot)
        logger.info("[1/4] Initializing PersonalAssistantEngine...")
        from ...adapters.cli.app import _load_config

        config = _load_config()
        engine = PersonalAssistantEngine(config)
        await engine.initialize()
        logger.info("      ✓ Engine initialized")

        # Set up API dependencies
        logger.info("[2/4] Setting up API authentication...")
        set_dependencies(engine, TELEGRAM_BOT_TOKEN)
        logger.info("      ✓ API dependencies ready")

        # Start daemon (background task)
        logger.info("[3/4] Starting daemon service...")
        daemon = PersonalAssistantDaemon(config)
        await daemon.initialize()
        daemon_task = asyncio.create_task(daemon.run())
        _tasks["daemon"] = daemon_task
        logger.info("      ✓ Daemon started")

        # Start Telegram bot (background task)
        logger.info("[4/4] Starting Telegram bot...")
        bot_handler = TelegramBotHandler(TELEGRAM_BOT_TOKEN, engine, MINI_APP_URL)
        bot_task = asyncio.create_task(bot_handler.start_polling())
        _tasks["bot"] = bot_task
        logger.info("      ✓ Bot started (long-polling)")

        logger.info("=" * 70)
        logger.info(f"Backend running at http://{API_HOST}:{API_PORT}")
        logger.info(f"Mini App URL: {MINI_APP_URL}")
        logger.info(f"Telegram Bot Token: {TELEGRAM_BOT_TOKEN[:10]}...")
        logger.info("=" * 70)

        yield

    finally:
        logger.info("Shutting down...")

        # Cancel all tasks with timeout
        for name, task in _tasks.items():
            if not task.done():
                logger.info(f"Stopping {name}...")
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=5.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    logger.warning(f"{name} did not shut down cleanly, forcing...")

        # Clean up engine
        if "engine" in locals():
            try:
                await asyncio.wait_for(engine.shutdown(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Engine shutdown timed out")

        logger.info("Shutdown complete")


def create_app() -> FastAPI:
    """Create the FastAPI application."""
    app = FastAPI(
        title="Personal Assistant Telegram Mini App",
        description="Backend API for Telegram Mini App gateway",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Add CORS middleware (for Mini App WebView)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # TODO: Restrict to MINI_APP_URL in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API routes
    app.include_router(router)

    return app


app = create_app()


async def main() -> None:
    """Run the unified service."""
    # Create Uvicorn config
    config = Config(
        app=app,
        host=API_HOST,
        port=API_PORT,
        log_level="info",
    )
    server = Server(config)

    # Run the server (blocking)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
