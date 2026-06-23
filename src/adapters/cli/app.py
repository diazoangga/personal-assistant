"""CLI Adapter - Typer + Rich interface."""

import asyncio
import os
from typing import Optional

from dotenv import load_dotenv
import typer

# Load environment variables at module import time, before any config is read
load_dotenv()
from rich.console import Console
from rich.live import Live
from rich.panel import Panel

from ...core.bus import EventBus
from ...core.commands import (
    Ask,
    Brainstorm,
    ResearchTopic,
    Opportunities,
    Feedback,
    ShowInterests,
    ShowDigest,
    IngestNow,
)
from ...core.events import Event, Started, Progress, Message, Result
from ...main_engine import PersonalAssistantEngine
from ...daemon.manager import DaemonManager

app = typer.Typer(
    name="pa",
    help="AI Personal Assistant - CLI Interface",
    add_completion=False,
)

console = Console()

# Global engine reference
_engine: Optional[PersonalAssistantEngine] = None


def _load_config() -> dict:
    """Load all configuration from environment variables.

    All configuration is now environment-driven (.env file) for better
    flexibility, security, and deployment across different environments.
    Environment variables are loaded at module import time via load_dotenv().
    """

    # Helper to parse comma-separated values
    def parse_list(env_var: str, default: list[str]) -> list[str]:
        val = os.getenv(env_var)
        if val:
            return [s.strip() for s in val.split(",")]
        return default

    def parse_bool(env_var: str, default: bool = False) -> bool:
        val = os.getenv(env_var, "").lower()
        if val in ("true", "1", "yes", "on"):
            return True
        if val in ("false", "0", "no", "off"):
            return False
        return default

    def parse_int(env_var: str, default: int) -> int:
        try:
            return int(os.getenv(env_var, str(default)))
        except (ValueError, TypeError):
            return default

    def parse_float(env_var: str, default: float) -> float:
        try:
            return float(os.getenv(env_var, str(default)))
        except (ValueError, TypeError):
            return default

    # Build config dict entirely from environment variables
    config = {
        # Top-level API keys and settings
        "openrouter_api_key": os.getenv("OPENROUTER_API_KEY", ""),
        "github_token": os.getenv("GITHUB_TOKEN", ""),
        "slack_bot_token": os.getenv("SLACK_BOT_TOKEN", ""),
        "slack_app_token": os.getenv("SLACK_APP_TOKEN", ""),
        "tavily_api_key": os.getenv("TAVILY_API_KEY", ""),

        # General settings
        "general": {
            "name": os.getenv("APP_NAME", "My AI Assistant"),
            "timezone": os.getenv("APP_TIMEZONE", "UTC"),
            "language": os.getenv("APP_LANGUAGE", "en"),
        },

        # LLM configuration
        "llm": {
            "provider": "openrouter",
            "base_url": os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            "meta_model": os.getenv("OPENROUTER_META_MODEL", "google/gemma-4-26b-a4b-it:free"),
            "reasoning_model": os.getenv("OPENROUTER_REASONING_MODEL", "google/gemma-4-26b-a4b-it:free"),
            "embedding_model": os.getenv("OPENROUTER_EMBEDDING_MODEL", "qwen/qwen3-embedding-8b"),
            "rate_limit_per_minute": parse_int("OPENROUTER_RATE_LIMIT_PER_MINUTE", 60),
            "rate_limit_per_day": parse_int("OPENROUTER_RATE_LIMIT_PER_DAY", 1000),
            "max_retries": parse_int("OPENROUTER_MAX_RETRIES", 3),
            "retry_base_delay": parse_float("OPENROUTER_RETRY_BASE_DELAY", 1.0),
        },

        # Storage configuration
        "storage": {
            "qdrant_host": os.getenv("QDRANT_HOST", "localhost"),
            "qdrant_port": parse_int("QDRANT_PORT", 6333),
            "qdrant_collection": os.getenv("QDRANT_COLLECTION", "personal-assistant-kb"),
            "knowledge_db": os.getenv("KNOWLEDGE_DB_PATH", "./data/knowledge.db"),
        },

        # Ingest pipeline configuration
        "ingest": {
            "github_enabled": parse_bool("GITHUB_ENABLED", True),
            "github_poll_interval_minutes": parse_int("GITHUB_POLL_INTERVAL_MINUTES", 15),
            "arxiv_enabled": parse_bool("ARXIV_ENABLED", True),
            "arxiv_categories": parse_list("ARXIV_CATEGORIES", ["cs.AI", "cs.LG", "cs.CL"]),
            "arxiv_max_results": parse_int("ARXIV_MAX_RESULTS", 50),
        },

        # Agents configuration
        "agents": {
            "meta_agent": parse_bool("AGENT_META_ENABLED", True),
            "interest_agent": parse_bool("AGENT_INTEREST_ENABLED", True),
            "research_agent": parse_bool("AGENT_RESEARCH_ENABLED", True),
            "opportunity_agent": parse_bool("AGENT_OPPORTUNITY_ENABLED", True),
            "brainstorming_agent": parse_bool("AGENT_BRAINSTORMING_ENABLED", True),
            "interest": {
                "batch_size": parse_int("INTEREST_BATCH_SIZE", 5),
                "min_confidence": parse_float("INTEREST_MIN_CONFIDENCE", 0.6),
                "embedding_cache_enabled": parse_bool("INTEREST_EMBEDDING_CACHE_ENABLED", True),
            },
            "brainstorming": {
                "temperature": parse_float("BRAINSTORMING_TEMPERATURE", 0.7),
                "max_iterations": parse_int("BRAINSTORMING_MAX_ITERATIONS", 5),
            },
        },

        # Knowledge storage configuration
        "knowledge": {
            "quality_threshold": parse_float("KNOWLEDGE_QUALITY_THRESHOLD", 0.65),
            "auto_embed": parse_bool("KNOWLEDGE_AUTO_EMBED", False),
            "max_entries_per_user": parse_int("KNOWLEDGE_MAX_ENTRIES_PER_USER", 1000),
        },

        # Conversation management
        "conversation": {
            "session_limit": parse_int("CONVERSATION_SESSION_LIMIT", 100),
            "auto_create": parse_bool("CONVERSATION_AUTO_CREATE", True),
            "persist_across_restarts": parse_bool("CONVERSATION_PERSIST_ACROSS_RESTARTS", True),
        },

        # Topics seed list
        "topics": {
            "seed_topics": parse_list(
                "SEED_TOPICS",
                [
                    "artificial intelligence",
                    "machine learning",
                    "software engineering",
                    "python",
                    "distributed systems",
                ],
            ),
        },

        # Daemon service configuration
        "daemon": {
            "check_interval_seconds": parse_int("DAEMON_CHECK_INTERVAL_SECONDS", 60),
            "ingest_interval_minutes": parse_int("DAEMON_INGEST_INTERVAL_MINUTES", 15),
            "log_level": os.getenv("DAEMON_LOG_LEVEL", "INFO"),
            "log_file": os.getenv("DAEMON_LOG_FILE", "./data/daemon.log"),
            "pid_file": os.getenv("DAEMON_PID_FILE", "./data/daemon.pid"),
            "state_file": os.getenv("DAEMON_STATE_FILE", "./data/daemon_state.json"),
        },

        # Connectors
        "connectors": {
            "slack": {
                "enabled": parse_bool("CONNECTOR_SLACK_ENABLED", False),
                "channels": parse_list("CONNECTOR_SLACK_CHANNELS", ["#general"]),
                "include_dms": parse_bool("CONNECTOR_SLACK_INCLUDE_DMS", True),
            },
            "browser": {
                "enabled": parse_bool("CONNECTOR_BROWSER_ENABLED", False),
                "browsers": parse_list("CONNECTOR_BROWSER_BROWSERS", ["chrome", "firefox"]),
                "track_searches": parse_bool("CONNECTOR_BROWSER_TRACK_SEARCHES", True),
                "track_page_visits": parse_bool("CONNECTOR_BROWSER_TRACK_PAGE_VISITS", True),
                "min_time_on_page": parse_int("CONNECTOR_BROWSER_MIN_TIME_ON_PAGE", 2),
                "exclude_domains": parse_list("CONNECTOR_BROWSER_EXCLUDE_DOMAINS", ["localhost", "127.0.0.1"]),
            },
        },
    }

    # Override brainstorming model if explicitly set
    brainstorming_model = os.getenv("BRAINSTORMING_MODEL")
    if brainstorming_model:
        config["agents"]["brainstorming"]["model"] = brainstorming_model

    return config


async def _get_engine() -> PersonalAssistantEngine:
    """Get or create the engine instance."""
    global _engine
    if _engine is None:
        config = _load_config()
        _engine = PersonalAssistantEngine(config)
        await _engine.initialize()
    return _engine


async def _stream_job(job_id: str, bus: EventBus) -> None:
    """Stream job events with Rich live rendering."""
    events = []
    done = asyncio.Event()

    async def consume_events():
        async for event in bus.subscribe(job_id):
            events.append(event)
            if isinstance(event, Result):
                done.set()
                break

    # Start consuming events
    consumer_task = asyncio.create_task(consume_events())

    try:
        with Live(console=console, refresh_per_second=4) as live:
            while not done.is_set():
                # Build status panel
                lines = []
                for ev in events:
                    if isinstance(ev, Started):
                        lines.append(f"[bold blue]⚙ Starting:[/] {ev.kind}")
                    elif isinstance(ev, Progress):
                        pct = f" ({ev.pct:.0f}%)" if ev.pct is not None else ""
                        lines.append(f"[yellow]⟳ {ev.phase}:[/] {ev.message}{pct}")
                    elif isinstance(ev, Message):
                        lines.append(f"[cyan]💬 {ev.text[:200]}[/]")
                    elif isinstance(ev, Result):
                        ok_str = "✓" if ev.ok else "✗"
                        lines.append(f"[green]{ok_str} Completed[/]")

                panel = Panel(
                    "\n".join(lines) if lines else "[dim]Waiting for events...[/]",
                    title=f"[bold]Job: {job_id}[/]",
                    border_style="blue",
                )
                live.update(panel)

                await asyncio.sleep(0.1)
    finally:
        await consumer_task


@app.command("ask")
def ask_cmd(question: str = typer.Argument(..., help="Your question")):
    """Ask a question."""
    asyncio.run(_ask(question))


async def _ask(question: str) -> None:
    """Internal ask implementation."""
    engine = await _get_engine()
    
    with console.status("[bold green]Thinking..."):
        answer = await engine.ask(question)
    
    console.print("\n[bold blue]Answer:[/]")
    console.print(answer)


@app.command("brainstorm")
def brainstorm_cmd(topic: str = typer.Argument(..., help="Topic to brainstorm")):
    """Start a brainstorming session."""
    asyncio.run(_brainstorm(topic))


async def _brainstorm(topic: str) -> None:
    """Internal brainstorm implementation."""
    import logging

    engine = await _get_engine()

    # Capture brainstorming logs for display
    logs: list[str] = []

    class BrainstormLogHandler(logging.Handler):
        """Custom handler to capture brainstorming execution logs."""

        def emit(self, record: logging.LogRecord) -> None:
            # Capture all logs from brainstorming submodules
            if "brainstorming" in record.name:
                # Extract message and only include logs with [Tool] or [Node] markers
                msg = record.getMessage()
                if msg.startswith("["):
                    logs.append(msg)

    # Attach handler to root brainstorming logger (catches all submodules)
    root_logger = logging.getLogger("src.agents.brainstorming")
    root_logger.setLevel(logging.DEBUG)
    handler = BrainstormLogHandler(level=logging.DEBUG)
    root_logger.addHandler(handler)
    root_logger.propagate = False  # Don't propagate to avoid duplicates

    try:
        with console.status("[bold green]Brainstorming..."):
            response = await engine.brainstorm(topic)

        # Display execution log
        if logs:
            console.print("\n[dim]━━━ Execution Trace ━━━[/]")
            for log in logs:
                if "Tool" in log or "tool" in log or "Calling" in log.lower():
                    console.print(f"[cyan]⚙ {log}[/]")
                elif "Registered" in log or "interest" in log.lower():
                    console.print(f"[green]✓ {log}[/]")
                elif "Safety" in log or "safety" in log.lower():
                    console.print(f"[yellow]🛡 {log}[/]")
                else:
                    console.print(f"[dim]→ {log}[/]")

        # Display execution log with color coding
        if logs:
            console.print("\n[dim]━━━ Execution Trace ━━━[/]")
            for log in logs:
                if "[Tool]" in log:
                    console.print(f"[cyan]⚙  {log}[/]")
                elif "[Node]" in log:
                    if "Registered" in log or "interest" in log.lower():
                        console.print(f"[green]✓  {log}[/]")
                    elif "BLOCKED" in log or "Safety" in log:
                        console.print(f"[yellow]🛡  {log}[/]")
                    elif "accepted" in log.lower() or "ALLOWED" in log:
                        console.print(f"[green]✓  {log}[/]")
                    elif "needs more" in log.lower():
                        console.print(f"[blue]↻  {log}[/]")
                    else:
                        console.print(f"[dim]→  {log}[/]")
                else:
                    console.print(f"[dim]{log}[/]")

        console.print("\n[bold blue]Ideas:[/]")
        console.print(response)
    finally:
        root_logger.removeHandler(handler)


@app.command("research")
def research_cmd(
    topic: str = typer.Argument(..., help="Topic to research"),
    depth: int = typer.Option(2, "--depth", "-d", min=1, max=5, help="Research depth"),
):
    """Deep research on a topic."""
    asyncio.run(_research(topic, depth))


async def _research(topic: str, depth: int) -> None:
    """Internal research implementation."""
    import logging

    engine = await _get_engine()

    # Capture research logs for display
    logs: list[str] = []

    class ResearchLogHandler(logging.Handler):
        """Custom handler to capture research execution logs."""

        def emit(self, record: logging.LogRecord) -> None:
            # Capture logs from research agent
            if "research" in record.name:
                msg = record.getMessage()
                # Include step logs and other important messages
                if msg.startswith("[") or "✅" in msg or "❌" in msg or "=" in msg:
                    logs.append(msg)

    # Attach handler to research logger (catches all submodules)
    root_logger = logging.getLogger("src.agents.research")
    root_logger.setLevel(logging.INFO)
    handler = ResearchLogHandler(level=logging.INFO)
    root_logger.addHandler(handler)
    root_logger.propagate = False  # Don't propagate to avoid duplicates

    try:
        with console.status(f"[bold green]Researching '{topic}' (depth={depth})..."):
            response = await engine.research(topic, depth=depth)

        # Display execution log
        if logs:
            console.print("\n[bold blue]Research Progress:[/]")
            for log_line in logs:
                # Color-code based on content
                if "RESEARCH AGENT:" in log_line:
                    console.print(f"[bold cyan]{log_line}[/]")
                elif "COMPLETE" in log_line:
                    console.print(f"[bold green]{log_line}[/]")
                elif "FAILED" in log_line:
                    console.print(f"[bold red]{log_line}[/]")
                elif "=" in log_line:
                    console.print(f"[dim]{log_line}[/]")
                else:
                    console.print(f"[cyan]{log_line}[/]")

        console.print("\n[bold blue]Research Summary:[/]")
        console.print(f"  📄 New papers: {response.new_papers}")
        console.print(f"  💡 New concepts: {response.new_concepts}")
        console.print(f"  🔗 Relationships: {response.new_edges}")
        if response.summary:
            console.print(f"\n[bold]Summary:[/]")
            console.print(f"  {response.summary[:200]}{'...' if len(response.summary) > 200 else ''}")

    finally:
        # Clean up handler
        root_logger.removeHandler(handler)


@app.command("ingest")
def ingest_cmd(
    connector: str = typer.Option("github", "--connector", "-c", help="Connector to use"),
):
    """Trigger activity ingestion."""
    asyncio.run(_ingest(connector))


async def _ingest(connector: str) -> None:
    """Internal ingest implementation."""
    engine = await _get_engine()
    
    with console.status("[bold green]Fetching activity..."):
        if connector == "github":
            stats = await engine.ingest_github()
        else:
            console.print(f"[red]Unknown connector: {connector}[/]")
            return
    
    console.print("\n[bold green]✓ Ingestion Complete[/]")
    console.print(f"Total signals: {stats.get('total', 0)}")
    
    if stats.get("by_type"):
        console.print("\nBy type:")
        for activity_type, count in stats["by_type"].items():
            console.print(f"  {activity_type}: {count}")
    
    if stats.get("by_repo"):
        console.print("\nBy repo:")
        for repo, count in list(stats["by_repo"].items())[:5]:
            console.print(f"  {repo}: {count}")


@app.command("interests")
def interests_cmd(
    show_all: bool = typer.Option(False, "--all", "-a", help="Show all interests"),
):
    """Show current interest graph."""
    asyncio.run(_interests(show_all))


async def _interests(show_all: bool) -> None:
    """Internal interests implementation."""
    engine = await _get_engine()
    
    min_strength = 0.0 if show_all else 0.3
    interests = await engine.get_interests(min_strength=min_strength)
    
    if not interests:
        console.print("[yellow]No interests tracked yet. Try ingesting GitHub activity![/]")
        return
    
    console.print(f"\n[bold blue]Your Interests ({len(interests)}):[/]")
    for interest in interests:
        strength_bar = "█" * int(interest["strength"] * 10)
        console.print(f"  {interest['label']:30} {strength_bar} ({interest['strength']:.2f})")


@app.command("status")
def status_cmd():
    """Show system status."""
    console.print("[bold]Personal Assistant Status[/]")
    console.print()
    
    config = _load_config()
    has_openrouter = bool(config.get("openrouter_api_key"))
    has_github = bool(config.get("github_token"))
    
    console.print(f"OpenRouter API: {'[green]Configured[/]' if has_openrouter else '[red]Missing[/]'}")
    console.print(f"GitHub Token:   {'[green]Configured[/]' if has_github else '[yellow]Not set (ingest won\'t work)[/]'}")
    console.print(f"Engine:         {'[green]Ready[/]' if _engine else '[yellow]Not initialized[/]'}")


@app.command("repl")
def repl_cmd():
    """Interactive REPL mode."""
    console.print("[bold blue]Personal Assistant REPL[/]")
    console.print("Commands: ask, brainstorm, research, ingest, interests, status, exit\n")

    while True:
        try:
            user_input = typer.prompt("pa>", default="").strip()
            if user_input.lower() in ("exit", "quit"):
                break
            if not user_input:
                continue

            parts = user_input.split(maxsplit=1)
            cmd_name = parts[0]
            args = parts[1] if len(parts) > 1 else ""

            if cmd_name == "ask":
                asyncio.run(_ask(args))
            elif cmd_name == "brainstorm":
                asyncio.run(_brainstorm(args))
            elif cmd_name == "research":
                asyncio.run(_research(args, depth=2))
            elif cmd_name == "ingest":
                asyncio.run(_ingest("github"))
            elif cmd_name == "interests":
                asyncio.run(_interests(show_all=False))
            elif cmd_name == "status":
                status_cmd()
            else:
                console.print(f"[red]Unknown command: {cmd_name}[/]")
                console.print("Available: ask, brainstorm, research, ingest, interests, status, exit")

        except KeyboardInterrupt:
            console.print("\n[dim]Use 'exit' to quit[/]")
        except Exception as e:
            import traceback
            console.print(f"[red]Error: {e}[/]")
            console.print(f"[dim]{traceback.format_exc()}[/]")


daemon_app = typer.Typer(help="Daemon management (background 24/7 service)")
app.add_typer(daemon_app, name="daemon")


@daemon_app.command("start")
def daemon_start(foreground: bool = typer.Option(False, "--foreground", "-f", help="Run in foreground (debugging)")):
    """Start the background daemon."""
    config = _load_config()
    manager = DaemonManager(config)
    asyncio.run(manager.start(foreground=foreground))


@daemon_app.command("stop")
def daemon_stop(force: bool = typer.Option(False, "--force", "-f", help="Force stop (SIGKILL)")):
    """Stop the background daemon."""
    config = _load_config()
    manager = DaemonManager(config)
    asyncio.run(manager.stop(force=force))


@daemon_app.command("status")
def daemon_status():
    """Check daemon status."""
    config = _load_config()
    manager = DaemonManager(config)
    manager.status()


@daemon_app.command("logs")
def daemon_logs(follow: bool = typer.Option(False, "--follow", "-f", help="Tail logs (Ctrl+C to stop)"),
                lines: int = typer.Option(50, "--lines", "-n", help="Number of lines to show")):
    """Show daemon logs."""
    config = _load_config()
    manager = DaemonManager(config)
    manager.logs(follow=follow, lines=lines)


@daemon_app.command("clear-logs")
def daemon_clear_logs():
    """Clear daemon logs."""
    config = _load_config()
    manager = DaemonManager(config)
    manager.reset_logs()


def main() -> None:
    """Entry point."""
    app()


if __name__ == "__main__":
    main()
