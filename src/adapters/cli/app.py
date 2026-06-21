"""CLI Adapter - Typer + Rich interface."""

import asyncio
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
import toml
import typer
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
    """Load configuration from settings.toml and .env."""
    # Load environment variables from .env file
    load_dotenv()
    
    config_path = Path(__file__).parent.parent.parent / "config" / "settings.toml"
    
    config = {}
    if config_path.exists():
        config = toml.load(config_path)
    
    # Merge with environment variables
    config["openrouter_api_key"] = os.getenv("OPENROUTER_API_KEY", "")
    config["github_token"] = os.getenv("GITHUB_TOKEN", "")
    
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
    engine = await _get_engine()
    
    with console.status("[bold green]Brainstorming..."):
        response = await engine.brainstorm(topic)
    
    console.print("\n[bold blue]Ideas:[/]")
    console.print(response)


@app.command("research")
def research_cmd(
    topic: str = typer.Argument(..., help="Topic to research"),
    depth: int = typer.Option(2, "--depth", "-d", min=1, max=5, help="Research depth"),
):
    """Deep research on a topic."""
    asyncio.run(_research(topic, depth))


async def _research(topic: str, depth: int) -> None:
    """Internal research implementation."""
    engine = await _get_engine()
    
    with console.status(f"[bold green]Researching (depth={depth})..."):
        response = await engine.research(topic, depth=depth)
    
    console.print("\n[bold blue]Research Summary:[/]")
    console.print(response)


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
