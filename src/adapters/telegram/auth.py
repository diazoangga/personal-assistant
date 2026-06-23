"""Telegram Mini App authentication via initData HMAC validation."""

import hashlib
import hmac
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class TelegramInitDataValidator:
    """Validates Telegram Mini App initData using HMAC-SHA256."""

    def __init__(self, bot_token: str):
        """
        Args:
            bot_token: Telegram bot token (used to derive the secret key)
        """
        self.bot_token = bot_token
        # Secret key = HMAC_SHA256("WebAppData", bot_token)
        self.secret_key = hmac.new(
            b"WebAppData",
            bot_token.encode(),
            hashlib.sha256
        ).digest()

    def validate(self, init_data: str, max_age_seconds: int = 300) -> Optional[dict[str, str]]:
        """
        Validate Telegram Mini App initData.

        Args:
            init_data: The initData string from Telegram (URL-encoded key=value pairs)
            max_age_seconds: Maximum age of the data_check_string timestamp (default: 5 min)

        Returns:
            Dict of parsed initData fields (includes 'user' JSON), or None if invalid
        """
        try:
            # Parse the init_data string
            params = {}
            for item in init_data.split("&"):
                if "=" not in item:
                    continue
                key, value = item.split("=", 1)
                params[key] = value

            if "hash" not in params:
                logger.warning("No hash in initData")
                return None

            received_hash = params.pop("hash")

            # Check auth_date is recent (prevent replay attacks)
            if "auth_date" in params:
                auth_date = int(params["auth_date"])
                current_time = int(time.time())
                if current_time - auth_date > max_age_seconds:
                    logger.warning(f"initData too old: {current_time - auth_date}s")
                    return None

            # Rebuild the data_check_string (same order as Telegram docs)
            data_check_string = "\n".join(
                f"{k}={params[k]}"
                for k in sorted(params.keys())
            )

            # Compute HMAC
            computed_hash = hmac.new(
                self.secret_key,
                data_check_string.encode(),
                hashlib.sha256
            ).hexdigest()

            # Timing-safe comparison
            if not hmac.compare_digest(computed_hash, received_hash):
                logger.warning("Hash mismatch")
                return None

            logger.debug(f"initData validated for user")
            return params

        except Exception as e:
            logger.error(f"Error validating initData: {e}")
            return None

    def extract_user_id(self, params: dict[str, str]) -> Optional[str]:
        """Extract Telegram user ID from validated initData params."""
        import json
        import urllib.parse

        if "user" not in params:
            return None

        try:
            user_json = urllib.parse.unquote(params["user"])
            user_obj = json.loads(user_json)
            return str(user_obj.get("id"))
        except Exception as e:
            logger.error(f"Error extracting user ID: {e}")
            return None
