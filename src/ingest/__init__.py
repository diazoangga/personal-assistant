"""Ingest package - Activity sensing pipeline."""

from .pipeline import IngestPipeline
from .connectors.github import GitHubConnector

__all__ = ["IngestPipeline", "GitHubConnector"]
