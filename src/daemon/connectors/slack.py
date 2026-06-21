"""Slack activity connector."""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from ..connector_base import ActivityConnector, ActivitySignal

logger = logging.getLogger(__name__)


class SlackConnector(ActivityConnector):
    """Fetches Slack messages from joined channels and DMs."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.name = "slack"
        self.token = config.get("slack_bot_token", "")
        self.api_base = "https://slack.com/api"
        self.timeout = 30

    async def fetch(self, since: Optional[datetime] = None) -> List[ActivitySignal]:
        """
        Fetch Slack messages from joined channels and DMs.

        Args:
            since: Only return messages after this timestamp

        Returns:
            List of ActivitySignal objects
        """
        if not self.token:
            logger.debug("Slack connector disabled: no slack_bot_token configured")
            return []

        if not self.enabled:
            return []

        signals = []

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Fetch list of channels
                channels = await self._get_channels(client)

                # Fetch messages from each channel
                for channel_id in channels:
                    messages = await self._fetch_channel_messages(
                        client, channel_id, since
                    )
                    signals.extend(messages)

                # Fetch direct messages
                dm_messages = await self._fetch_direct_messages(client, since)
                signals.extend(dm_messages)

        except Exception as e:
            logger.error(f"Slack connector error: {e}", exc_info=True)

        return signals

    async def _get_channels(self, client: httpx.AsyncClient) -> List[str]:
        """
        Get list of joined channel IDs.

        Args:
            client: HTTP client

        Returns:
            List of channel IDs
        """
        try:
            response = await client.get(
                f"{self.api_base}/conversations.list",
                headers=self._get_headers(),
                params={"types": "public_channel,private_channel", "limit": 100},
            )
            response.raise_for_status()
            data = response.json()

            if not data.get("ok"):
                logger.error(
                    f"Slack API error: {data.get('error', 'unknown error')}"
                )
                return []

            return [c["id"] for c in data.get("channels", [])]

        except Exception as e:
            logger.error(f"Failed to fetch Slack channels: {e}")
            return []

    async def _fetch_channel_messages(
        self,
        client: httpx.AsyncClient,
        channel_id: str,
        since: Optional[datetime] = None,
    ) -> List[ActivitySignal]:
        """
        Fetch messages from a specific channel.

        Args:
            client: HTTP client
            channel_id: Channel ID
            since: Only fetch messages after this timestamp

        Returns:
            List of ActivitySignal objects
        """
        signals = []

        try:
            params = {"channel": channel_id, "limit": 100}

            # Convert since timestamp to Slack's Unix timestamp format
            if since:
                params["oldest"] = str(since.timestamp())

            response = await client.get(
                f"{self.api_base}/conversations.history",
                headers=self._get_headers(),
                params=params,
            )
            response.raise_for_status()
            data = response.json()

            if not data.get("ok"):
                logger.debug(
                    f"Could not fetch messages from {channel_id}: {data.get('error')}"
                )
                return signals

            for message in data.get("messages", []):
                signal = self._parse_message(message, channel_id, is_dm=False)
                if signal:
                    signals.append(signal)

        except Exception as e:
            logger.error(f"Failed to fetch messages from channel {channel_id}: {e}")

        return signals

    async def _fetch_direct_messages(
        self, client: httpx.AsyncClient, since: Optional[datetime] = None
    ) -> List[ActivitySignal]:
        """
        Fetch direct messages.

        Args:
            client: HTTP client
            since: Only fetch messages after this timestamp

        Returns:
            List of ActivitySignal objects
        """
        signals = []

        try:
            # Get list of DM conversations
            response = await client.get(
                f"{self.api_base}/conversations.list",
                headers=self._get_headers(),
                params={"types": "im", "limit": 100},
            )
            response.raise_for_status()
            data = response.json()

            if not data.get("ok"):
                logger.debug(f"Could not fetch DMs: {data.get('error')}")
                return signals

            # Fetch messages from each DM
            for conversation in data.get("channels", []):
                channel_id = conversation["id"]
                messages = await self._fetch_channel_messages(
                    client, channel_id, since
                )
                # Mark these as DMs
                for signal in messages:
                    signal.data["is_dm"] = True
                signals.extend(messages)

        except Exception as e:
            logger.error(f"Failed to fetch direct messages: {e}")

        return signals

    def _parse_message(
        self, message: Dict[str, Any], channel_id: str, is_dm: bool = False
    ) -> Optional[ActivitySignal]:
        """
        Parse a Slack message into an ActivitySignal.

        Args:
            message: Slack message object
            channel_id: ID of the channel/DM
            is_dm: Whether this is a direct message

        Returns:
            ActivitySignal or None if message should be skipped
        """
        # Skip messages from bots and certain system messages
        if message.get("type") != "message" or message.get("subtype") in [
            "bot_message",
            "channel_topic",
            "channel_purpose",
        ]:
            return None

        user = message.get("user", "unknown")
        text = message.get("text", "")
        ts = message.get("ts", "")

        if not text or not ts:
            return None

        # Convert Slack timestamp to datetime
        try:
            timestamp = datetime.fromtimestamp(float(ts))
        except (ValueError, TypeError):
            timestamp = datetime.now()

        # Create human-readable description
        if is_dm:
            description = f"Slack DM from {user}: {text[:60]}"
        else:
            description = f"Slack message in #{channel_id} from {user}: {text[:60]}"

        return ActivitySignal(
            source="slack",
            event_type="message",
            timestamp=timestamp,
            data={
                "channel": channel_id,
                "user": user,
                "text": text,
                "is_dm": is_dm,
                "thread_ts": message.get("thread_ts"),
            },
            user_id=user,
            description=description,
        )

    def _get_headers(self) -> Dict[str, str]:
        """Get HTTP headers for Slack API requests."""
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
