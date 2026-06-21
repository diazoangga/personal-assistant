"""GitHub activity connector."""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from ..connector_base import ActivityConnector, ActivitySignal

logger = logging.getLogger(__name__)


class GitHubConnector(ActivityConnector):
    """Fetches GitHub activity (commits, PRs, issues, etc.)."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.name = "github"
        self.token = config.get("github_token", "")
        self.username = config.get("github_username", "")
        self.api_base = "https://api.github.com"

    async def fetch(self, since: Optional[datetime] = None) -> List[ActivitySignal]:
        """Fetch GitHub activity events."""
        if not self.token or not self.username:
            return []

        signals = []

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                headers = {
                    "Authorization": f"token {self.token}",
                    "Accept": "application/vnd.github.v3+json",
                }

                # Fetch user events
                url = f"{self.api_base}/users/{self.username}/events"
                params = {"per_page": 30}
                if since:
                    params["since"] = since.isoformat()

                response = await client.get(url, headers=headers, params=params)
                response.raise_for_status()
                events = response.json()

                for event in events:
                    signal = self._parse_event(event)
                    if signal:
                        signals.append(signal)

        except Exception as e:
            logger.error(f"GitHub connector error: {e}", exc_info=True)

        return signals

    def _parse_event(self, event: Dict[str, Any]) -> Optional[ActivitySignal]:
        """Parse a GitHub event into an ActivitySignal."""
        event_type = event.get("type", "")
        repo = event.get("repo", {})
        repo_name = repo.get("name", "")
        created_at = event.get("created_at", "")

        # Map GitHub event types to our signal types
        event_type_map = {
            "PushEvent": "commit",
            "PullRequestEvent": "pull_request",
            "IssuesEvent": "issue",
            "CreateEvent": "create",
            "DeleteEvent": "delete",
            "PullRequestReviewEvent": "review",
            "IssueCommentEvent": "comment",
            "CommitCommentEvent": "commit_comment",
        }

        signal_type = event_type_map.get(event_type)
        if not signal_type:
            return None

        # Parse timestamp
        try:
            timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            timestamp = datetime.now()

        # Extract relevant data
        payload = event.get("payload", {})
        description = f"{self.username} {signal_type} on {repo_name}"

        # Build description with more details
        if signal_type == "commit":
            commits = payload.get("commits", [])
            if commits:
                description += f": {len(commits)} commit(s)"
        elif signal_type == "pull_request":
            action = payload.get("action", "")
            pr = payload.get("pull_request", {})
            title = pr.get("title", "")
            description += f": {action} PR - {title}"
        elif signal_type == "issue":
            action = payload.get("action", "")
            issue = payload.get("issue", {})
            title = issue.get("title", "")
            description += f": {action} issue - {title}"

        return ActivitySignal(
            source="github",
            event_type=signal_type,
            timestamp=timestamp,
            data={
                "repository": repo_name,
                "event_type": event_type,
                "payload": payload,
            },
            user_id=self.username,
            description=description,
        )
