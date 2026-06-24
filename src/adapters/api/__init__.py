"""Local web API adapter for the Personal Assistant desktop (Tauri) app.

Exposes the engine over a loopback HTTP server (REST + SSE + WebSocket) and runs
the daemon in the same process. Replaces the deleted Telegram Mini App gateway.

See docs/WEB_API.md for the contract.
"""

from .app import create_app, main

__all__ = ["create_app", "main"]
