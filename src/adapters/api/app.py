"""FastAPI application for the local web API.

Runs the engine, the daemon, and the REST/SSE/WS server in one process, sharing a
single knowledge store. Bind loopback only; this is a local desktop backend.

Run it:
    python -m src.adapters.api
    # or
    poetry run python -m src.adapters.api
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ...daemon.service import PersonalAssistantDaemon
from ...main_engine import PersonalAssistantEngine
from .deps import set_dependencies
from .hub import EventHub

load_dotenv()

logger = logging.getLogger(__name__)

API_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 70)
    logger.info("Starting Personal Assistant local web API")
    logger.info("=" * 70)

    # Build config from the same environment-driven loader the CLI uses.
    from ..cli.app import _load_config

    config = _load_config()

    # Engine for serving API requests.
    logger.info("[1/3] Initializing engine...")
    engine = PersonalAssistantEngine(config)
    await engine.initialize()

    # Daemon (runs in-process, shares the same knowledge.db on disk).
    logger.info("[2/3] Starting daemon...")
    daemon = PersonalAssistantDaemon(config)
    await daemon.initialize()
    daemon_task = asyncio.create_task(daemon.run())

    # Wire dependencies.
    logger.info("[3/3] Wiring API dependencies...")
    hub = EventHub()
    set_dependencies(
        engine=engine,
        hub=hub,
        daemon=daemon,
        config=config,
        token=os.getenv("LOCAL_API_TOKEN") or None,
        user=os.getenv("LOCAL_API_USER", "local"),
    )

    host = os.getenv("LOCAL_API_HOST", "127.0.0.1")
    port = os.getenv("LOCAL_API_PORT", "8787")
    logger.info("=" * 70)
    logger.info("API ready at http://%s:%s  (docs at /docs)", host, port)
    logger.info("=" * 70)

    try:
        yield
    finally:
        logger.info("Shutting down...")
        daemon.running = False
        daemon_task.cancel()
        try:
            await asyncio.wait_for(daemon_task, timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        try:
            await asyncio.wait_for(engine.shutdown(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Engine shutdown timed out")
        logger.info("Shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Personal Assistant — Local Web API",
        description="Loopback API for the Personal Assistant desktop (Tauri) app.",
        version=API_VERSION,
        lifespan=lifespan,
    )

    # CORS for the Tauri WebView (dev Vite origin + packaged tauri origins).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:1420",
            "http://127.0.0.1:1420",
            "http://localhost:5173",
            "tauri://localhost",
            "https://tauri.localhost",
        ],
        allow_origin_regex=r"^(https?|tauri)://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers (imported here to avoid import-time side effects).
    from . import commands, queries, streams

    app.include_router(queries.router)
    app.include_router(commands.router)
    app.include_router(streams.router)

    return app


app = create_app()


def main() -> None:
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    host = os.getenv("LOCAL_API_HOST", "127.0.0.1")
    port = int(os.getenv("LOCAL_API_PORT", "8787"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
