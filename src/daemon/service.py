"""Core daemon service for continuous monitoring and activity ingestion."""

import asyncio
import logging
import signal
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..main_engine import PersonalAssistantEngine
from .connector_base import ActivityConnector, get_enabled_connectors


class DaemonConfig:
    """Daemon configuration."""

    def __init__(self, config: dict[str, Any]):
        self.config = config

        # Daemon-specific settings
        self.check_interval = config.get("daemon", {}).get("check_interval_seconds", 60)
        self.ingest_interval = config.get("daemon", {}).get("ingest_interval_minutes", 15)
        self.log_level = config.get("daemon", {}).get("log_level", "INFO")
        self.log_file = Path(config.get("daemon", {}).get("log_file", "./data/daemon.log"))
        self.pid_file = Path(config.get("daemon", {}).get("pid_file", "./data/daemon.pid"))
        self.state_file = Path(config.get("daemon", {}).get("state_file", "./data/daemon_state.json"))


class PersonalAssistantDaemon:
    """
    Background daemon service for the Personal Assistant.

    Runs 24/7 to:
    - Continuously monitor user activity across multiple sources
    - Trigger periodic ingestion of activity signals
    - Keep the Interest Agent updated with user behavior
    - Feed data into the recommendation engine
    """

    def __init__(self, config: dict[str, Any]):
        self.config = DaemonConfig(config)
        self.engine: Optional[PersonalAssistantEngine] = None
        self.running = False
        self._setup_logging()
        self._last_ingest = datetime.now() - timedelta(minutes=self.config.ingest_interval)
        self.logger.info("PersonalAssistantDaemon initialized")

    def _setup_logging(self) -> None:
        """Configure logging for the daemon."""
        self.config.log_file.parent.mkdir(parents=True, exist_ok=True)

        self.logger = logging.getLogger("personal-assistant-daemon")
        self.logger.setLevel(getattr(logging, self.config.log_level))

        # File handler
        fh = logging.FileHandler(self.config.log_file)
        fh.setLevel(getattr(logging, self.config.log_level))

        # Console handler
        ch = logging.StreamHandler()
        ch.setLevel(getattr(logging, self.config.log_level))

        # Formatter
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)

        self.logger.addHandler(fh)
        self.logger.addHandler(ch)

    async def initialize(self) -> None:
        """Initialize the daemon and engine."""
        try:
            self.logger.info("Initializing engine...")
            self.engine = PersonalAssistantEngine(self.config.config)
            await self.engine.initialize()
            self.logger.info("Engine initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize engine: {e}", exc_info=True)
            raise

    async def shutdown(self) -> None:
        """Gracefully shutdown the daemon."""
        self.logger.info("Shutting down daemon...")
        self.running = False

        if self.engine:
            try:
                await self.engine.shutdown()
                self.logger.info("Engine shutdown complete")
            except Exception as e:
                self.logger.error(f"Error during engine shutdown: {e}", exc_info=True)

    def register_connector(self, connector: ActivityConnector) -> None:
        """
        Register an activity connector.

        Args:
            connector: ActivityConnector instance
        """
        self.logger.info(f"Connector registered: {connector.name}")

    async def run(self) -> None:
        """Main daemon loop."""
        self.running = True
        self.logger.info(f"Starting daemon loop (check interval: {self.config.check_interval}s, ingest interval: {self.config.ingest_interval}m)")

        # Setup signal handlers for graceful shutdown
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))

        try:
            while self.running:
                try:
                    # Check if it's time to ingest
                    now = datetime.now()
                    elapsed = (now - self._last_ingest).total_seconds()

                    if elapsed >= self.config.ingest_interval * 60:
                        await self._run_ingest_cycle()
                        self._last_ingest = now

                    # Run connector checks (can be more frequent)
                    await self._check_connectors()

                    # Sleep before next iteration
                    await asyncio.sleep(self.config.check_interval)

                except Exception as e:
                    self.logger.error(f"Error in daemon loop: {e}", exc_info=True)
                    # Continue running even on errors
                    await asyncio.sleep(self.config.check_interval)

        except asyncio.CancelledError:
            self.logger.info("Daemon cancelled")
        finally:
            await self.shutdown()

    async def _run_ingest_cycle(self) -> None:
        """Run one cycle of activity ingestion."""
        if not self.engine:
            self.logger.warning("Engine not initialized, skipping ingest cycle")
            return

        start_time = time.time()
        self.logger.info("Starting ingest cycle...")

        try:
            # Ingest from all enabled connectors
            all_signals = []
            connectors = get_enabled_connectors()

            for connector in connectors:
                try:
                    self.logger.debug(f"Fetching signals from {connector.name}...")
                    signals = await connector.fetch(since=self._last_ingest)
                    all_signals.extend(signals)
                    self.logger.debug(f"Got {len(signals)} signals from {connector.name}")
                except Exception as e:
                    self.logger.error(
                        f"Error fetching from {connector.name}: {e}",
                        exc_info=True
                    )
                    continue

            if all_signals:
                self.logger.info(f"Processing {len(all_signals)} signals...")
                # TODO: Feed signals into the interest agent
                # For now, just log them
                self.logger.info(f"Ingest cycle: {len(all_signals)} signals processed")
            else:
                self.logger.debug("No new signals to process")

            elapsed = time.time() - start_time
            self.logger.info(f"Ingest cycle completed in {elapsed:.2f}s")

        except Exception as e:
            self.logger.error(f"Error during ingest cycle: {e}", exc_info=True)

    async def _check_connectors(self) -> None:
        """Check all connectors for realtime updates."""
        # This is called more frequently than _run_ingest_cycle
        # Useful for connectors that need realtime updates (Slack messages, browser tabs, etc.)
        pass

    def write_pid(self) -> None:
        """Write daemon PID to file."""
        self.config.pid_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config.pid_file, "w") as f:
            f.write(str(asyncio.os.getpid()))
        self.logger.info(f"PID written to {self.config.pid_file}")

    def read_pid(self) -> Optional[int]:
        """Read daemon PID from file."""
        if self.config.pid_file.exists():
            try:
                return int(self.config.pid_file.read_text().strip())
            except (ValueError, OSError):
                return None
        return None

    def remove_pid(self) -> None:
        """Remove PID file."""
        if self.config.pid_file.exists():
            self.config.pid_file.unlink()
            self.logger.info(f"PID file removed")


if __name__ == "__main__":
    """Run daemon directly (for subprocess)."""
    import sys
    from .service import PersonalAssistantDaemon
    from ..config.loader import load_config

    config = load_config()
    daemon = PersonalAssistantDaemon(config)

    async def run():
        await daemon.initialize()
        daemon.write_pid()
        try:
            await daemon.run()
        except KeyboardInterrupt:
            pass
        finally:
            daemon.remove_pid()

    asyncio.run(run())
