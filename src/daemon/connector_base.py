"""Base class and registry for activity connectors."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class ActivitySignal:
    """A single user activity event."""

    source: str  # "vscode", "browser", "slack", "github", etc.
    event_type: str  # "file_changed", "message", "commit", etc.
    timestamp: datetime
    data: Dict[str, Any]  # Event-specific data
    user_id: Optional[str] = None
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for storage."""
        return {
            "source": self.source,
            "event_type": self.event_type,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
            "user_id": self.user_id,
            "description": self.description,
        }


class ActivityConnector(ABC):
    """
    Base class for activity connectors.

    Subclasses should implement fetch() to return activity signals from a specific source.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize connector.

        Args:
            config: Connector-specific configuration
        """
        self.config = config
        self.name = self.__class__.__name__
        self.enabled = config.get("enabled", True)

    @abstractmethod
    async def fetch(self, since: Optional[datetime] = None) -> List[ActivitySignal]:
        """
        Fetch activity signals from this source.

        Args:
            since: Only return signals after this timestamp (for delta queries)

        Returns:
            List of ActivitySignal objects
        """
        pass

    async def initialize(self) -> None:
        """Initialize the connector (authenticate, setup, etc.)."""
        pass

    async def shutdown(self) -> None:
        """Cleanup when daemon shuts down."""
        pass


class ConnectorRegistry:
    """Registry for activity connectors."""

    def __init__(self):
        self._connectors: Dict[str, ActivityConnector] = {}

    def register(self, connector: ActivityConnector) -> None:
        """Register a connector."""
        self._connectors[connector.name] = connector

    def unregister(self, name: str) -> None:
        """Unregister a connector."""
        if name in self._connectors:
            del self._connectors[name]

    def get(self, name: str) -> Optional[ActivityConnector]:
        """Get a connector by name."""
        return self._connectors.get(name)

    def get_all(self) -> List[ActivityConnector]:
        """Get all registered connectors."""
        return list(self._connectors.values())

    def get_enabled(self) -> List[ActivityConnector]:
        """Get all enabled connectors."""
        return [c for c in self._connectors.values() if c.enabled]


# Global registry instance
_registry = ConnectorRegistry()


def register_connector(connector: ActivityConnector) -> None:
    """Register a connector globally."""
    _registry.register(connector)


def get_connector(name: str) -> Optional[ActivityConnector]:
    """Get a connector by name."""
    return _registry.get(name)


def get_all_connectors() -> List[ActivityConnector]:
    """Get all registered connectors."""
    return _registry.get_all()


def get_enabled_connectors() -> List[ActivityConnector]:
    """Get all enabled connectors."""
    return _registry.get_enabled()
