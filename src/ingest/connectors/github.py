"""GitHub Connector - Fetch user activity from GitHub."""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from github import Github
from github.Repository import Repository
from github.GitAuthor import GitAuthor

logger = logging.getLogger(__name__)


@dataclass
class RawSignal:
    """A raw activity signal from GitHub."""

    id: str
    connector: str  # "github"
    activity_type: str  # "commit", "pr", "issue", "review"
    repo_name: str
    description: str
    timestamp: str  # ISO format
    url: Optional[str]
    metadata: dict[str, Any] = field(default_factory=dict)


class GitHubConnector:
    """
    GitHub connector for fetching user activity.

    Fetches:
    - Commits from user's repositories
    - Pull requests (created and reviewed)
    - Issues (created and commented)
    - Code reviews

    Configuration:
    - github_token: Personal Access Token from environment
    - username: GitHub username (optional, uses token owner if not provided)
    - since: Fetch activities since this date (default: 7 days ago)
    - max_repos: Maximum number of repos to fetch (default: 50)
    """

    def __init__(self, config: dict[str, Any]):
        self.token = config.get("github_token") or os.getenv("GITHUB_TOKEN")
        self.username = config.get("github_username")
        self.since_days = config.get("since_days", 7)
        self.max_repos = config.get("max_repos", 50)

        if not self.token:
            raise ValueError(
                "GitHub token required. Set GITHUB_TOKEN env var or pass in config."
            )

        self._gh: Optional[Github] = None
        self._user: Any = None

    def connect(self) -> None:
        """Initialize GitHub connection."""
        self._gh = Github(self.token)
        self._user = self._gh.get_user()
        
        if not self.username:
            self.username = self._user.login

    def disconnect(self) -> None:
        """Close GitHub connection."""
        if self._gh:
            self._gh.close()
            self._gh = None
            self._user = None

    async def fetch(self) -> list[RawSignal]:
        """
        Fetch all user activity since configured date.

        Returns:
            List of RawSignal objects
        """
        if not self._gh:
            self.connect()

        signals = []
        since = datetime.utcnow() - timedelta(days=self.since_days)

        # Fetch from user's repositories
        repos = await self._get_repos()
        
        for repo in repos:
            repo_signals = await self._fetch_repo_activity(repo, since)
            signals.extend(repo_signals)

        # Fetch user-wide activities (PRs, issues, reviews)
        signals.extend(await self._fetch_user_activities(since))

        return signals

    async def _get_repos(self) -> list[Repository]:
        """Get user's repositories."""
        assert self._user is not None
        
        repos = []
        try:
            logger.debug(f"Fetching repositories for {self.username}...")
            for repo in self._user.get_repos(type="owner", sort="updated", direction="desc"):
                if len(repos) >= self.max_repos:
                    break
                repos.append(repo)
            logger.debug(f"Fetched {len(repos)} repositories")
        except Exception as e:
            logger.error(f"Error fetching repos: {e}", exc_info=True)
        
        return repos

    async def _fetch_repo_activity(
        self, repo: Repository, since: datetime
    ) -> list[RawSignal]:
        """Fetch activity from a single repository."""
        signals = []

        # Commits
        try:
            logger.debug(f"Fetching commits from {repo.full_name}...")
            commits = repo.get_commits(author=self.username, since=since)
            commit_count = 0
            for commit in commits[:100]:  # Limit per repo
                signal = RawSignal(
                    id=f"github:commit:{commit.sha}",
                    connector="github",
                    activity_type="commit",
                    repo_name=repo.full_name,
                    description=commit.commit.message.split("\n")[0][:200],
                    timestamp=commit.commit.author.date.isoformat(),
                    url=commit.html_url,
                    metadata={
                        "sha": commit.sha,
                        "files_changed": commit.stats.total if commit.stats else 0,
                        "additions": commit.stats.additions if commit.stats else 0,
                        "deletions": commit.stats.deletions if commit.stats else 0,
                    },
                )
                signals.append(signal)
                commit_count += 1
            logger.debug(f"Fetched {commit_count} commits from {repo.full_name}")
        except Exception as e:
            logger.error(f"Error fetching commits for {repo.full_name}: {e}", exc_info=True)

        return signals

    async def _fetch_user_activities(self, since: datetime) -> list[RawSignal]:
        """Fetch user-wide activities (PRs, issues, reviews)."""
        signals = []
        assert self._user is not None

        # Pull Requests created
        try:
            logger.debug("Fetching pull requests...")
            pr_count = 0
            issues = self._user.get_issues(filter="created", since=since, state="all")
            for issue in issues[:50]:
                if issue.pull_request:
                    signal = RawSignal(
                        id=f"github:pr:{issue.id}",
                        connector="github",
                        activity_type="pr",
                        repo_name=issue.repository.full_name,
                        description=f"Opened PR: {issue.title}",
                        timestamp=issue.created_at.isoformat(),
                        url=issue.html_url,
                        metadata={
                            "number": issue.number,
                            "state": issue.state,
                            "is_pr": True,
                        },
                    )
                    signals.append(signal)
                    pr_count += 1
            logger.debug(f"Fetched {pr_count} pull requests")
        except Exception as e:
            logger.error(f"Error fetching PRs: {e}", exc_info=True)

        # Issues created
        try:
            logger.debug("Fetching issues...")
            issue_count = 0
            issues = self._user.get_issues(filter="created", since=since, state="all")
            for issue in issues[:50]:
                if not issue.pull_request:
                    signal = RawSignal(
                        id=f"github:issue:{issue.id}",
                        connector="github",
                        activity_type="issue",
                        repo_name=issue.repository.full_name,
                        description=f"Created issue: {issue.title}",
                        timestamp=issue.created_at.isoformat(),
                        url=issue.html_url,
                        metadata={
                            "number": issue.number,
                            "state": issue.state,
                            "labels": [label.name for label in issue.labels],
                        },
                    )
                    signals.append(signal)
                    issue_count += 1
            logger.debug(f"Fetched {issue_count} issues")
        except Exception as e:
            logger.error(f"Error fetching issues: {e}", exc_info=True)

        return signals

    @staticmethod
    def classify_commit_message(message: str) -> dict[str, Any]:
        """
        Classify a commit message to extract intent.

        Returns:
            Dict with category, topics, is_learning, is_achievement
        """
        message_lower = message.lower()
        
        categories = {
            "feat": "feature",
            "fix": "bugfix",
            "docs": "documentation",
            "refactor": "refactoring",
            "test": "testing",
            "chore": "maintenance",
            "style": "styling",
            "perf": "performance",
        }

        category = "other"
        for prefix, cat in categories.items():
            if message_lower.startswith(prefix):
                category = cat
                break

        # Simple topic extraction
        topics = []
        tech_keywords = ["python", "javascript", "api", "database", "docker", "aws"]
        for keyword in tech_keywords:
            if keyword in message_lower:
                topics.append(keyword)

        # Heuristics for learning/achievement
        is_learning = any(w in message_lower for w in ["learn", "explore", "experiment", "try"])
        is_achievement = any(w in message_lower for w in ["complete", "finish", "implement", "add"])

        return {
            "category": category,
            "topics": topics,
            "is_learning": is_learning,
            "is_achievement": is_achievement,
        }
