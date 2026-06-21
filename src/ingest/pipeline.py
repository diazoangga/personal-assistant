"""Ingestion Pipeline - Orchestrates activity sensing."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .connectors.github import GitHubConnector, RawSignal

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    """Result of an ingestion run."""

    connector: str
    signals_count: int
    signals: list[RawSignal]
    started_at: str
    completed_at: str
    errors: list[str] = field(default_factory=list)


class IngestPipeline:
    """
    Orchestrates activity ingestion from multiple connectors.

    Usage:
        pipeline = IngestPipeline(config)
        result = await pipeline.run("github")
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._connectors: dict[str, Any] = {}

        # Initialize connectors based on config
        if config.get("github_enabled", True):
            self._connectors["github"] = GitHubConnector(config)

    async def run(self, connector_name: str | None = None) -> list[IngestResult]:
        """
        Run ingestion for specified connector or all enabled connectors.

        Args:
            connector_name: Specific connector to run (None = all)

        Returns:
            List of IngestResult objects
        """
        logger.info(f"Starting ingestion pipeline (connector={connector_name or 'all'})")
        results = []
        connectors_to_run = (
            [connector_name] if connector_name else list(self._connectors.keys())
        )

        for name in connectors_to_run:
            if name not in self._connectors:
                logger.warning(f"Connector '{name}' not found")
                results.append(
                    IngestResult(
                        connector=name,
                        signals_count=0,
                        signals=[],
                        started_at=datetime.utcnow().isoformat(),
                        completed_at=datetime.utcnow().isoformat(),
                        errors=[f"Connector '{name}' not found"],
                    )
                )
                continue

            logger.debug(f"Running connector: {name}")
            result = await self._run_connector(name)
            results.append(result)

        logger.info(f"Ingestion pipeline completed ({len(results)} connectors)")
        return results

    async def _run_connector(self, name: str) -> IngestResult:
        """Run a single connector."""
        connector = self._connectors[name]
        started_at = datetime.utcnow().isoformat()
        errors = []

        try:
            logger.debug(f"Connecting to {name}...")
            if hasattr(connector, "connect"):
                connector.connect()

            logger.debug(f"Fetching signals from {name}...")
            signals = await connector.fetch()
            logger.info(f"Fetched {len(signals)} signals from {name}")

            return IngestResult(
                connector=name,
                signals_count=len(signals),
                signals=signals,
                started_at=started_at,
                completed_at=datetime.utcnow().isoformat(),
                errors=errors,
            )
        except Exception as e:
            logger.error(f"Error running connector {name}: {e}", exc_info=True)
            errors.append(str(e))
            return IngestResult(
                connector=name,
                signals_count=0,
                signals=[],
                started_at=started_at,
                completed_at=datetime.utcnow().isoformat(),
                errors=errors,
            )
        finally:
            # Disconnect
            if hasattr(connector, "disconnect"):
                logger.debug(f"Disconnecting from {name}")
                connector.disconnect()

    async def process_signals(self, signals: list[RawSignal]) -> dict[str, Any]:
        """
        Process raw signals into structured activities.

        This is where you would:
        1. Classify activities (coding, reading, etc.)
        2. Extract topics
        3. Update interest graph
        4. Store in memory

        For now, returns basic statistics.
        """
        logger.debug(f"Processing {len(signals)} signals...")
        stats = {
            "total": len(signals),
            "by_type": {},
            "by_repo": {},
            "latest_timestamp": None,
        }

        for signal in signals:
            # Count by type
            stats["by_type"][signal.activity_type] = (
                stats["by_type"].get(signal.activity_type, 0) + 1
            )

            # Count by repo
            stats["by_repo"][signal.repo_name] = (
                stats["by_repo"].get(signal.repo_name, 0) + 1
            )

            # Track latest
            if signal.timestamp:
                if not stats["latest_timestamp"] or signal.timestamp > stats["latest_timestamp"]:
                    stats["latest_timestamp"] = signal.timestamp
        
        logger.info(f"Processed signals: {stats['total']} total, {len(stats['by_type'])} types, {len(stats['by_repo'])} repos")
        return stats

        return stats
