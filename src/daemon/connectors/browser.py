"""Browser activity connector for Chrome and Firefox."""

import logging
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from shutil import copy2

from ..connector_base import ActivityConnector, ActivitySignal

logger = logging.getLogger(__name__)


class BrowserConnector(ActivityConnector):
    """Monitors web search history and visited pages from Chrome and Firefox."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.name = "browser"
        self.browsers = config.get("browsers", ["chrome", "firefox"])
        self.include_searches = config.get("include_searches", True)
        self.include_page_visits = config.get("include_page_visits", True)

    async def fetch(self, since: Optional[datetime] = None) -> List[ActivitySignal]:
        """
        Fetch browser history (searches and page visits).

        Args:
            since: Only return entries after this timestamp

        Returns:
            List of ActivitySignal objects
        """
        if not self.enabled:
            return []

        signals = []
        since_timestamp = int(since.timestamp()) if since else 0

        try:
            if "chrome" in self.browsers:
                chrome_signals = await self._fetch_chrome_history(since_timestamp)
                signals.extend(chrome_signals)

            if "firefox" in self.browsers:
                firefox_signals = await self._fetch_firefox_history(since_timestamp)
                signals.extend(firefox_signals)

        except Exception as e:
            logger.error(f"Browser connector error: {e}", exc_info=True)

        return signals

    async def _fetch_chrome_history(self, since_timestamp: int) -> List[ActivitySignal]:
        """
        Fetch Chrome browsing history.

        Args:
            since_timestamp: Only return entries after this Unix timestamp

        Returns:
            List of ActivitySignal objects
        """
        signals = []
        chrome_paths = self._get_chrome_paths()

        for profile_path in chrome_paths:
            history_db = profile_path / "History"
            if not history_db.exists():
                continue

            try:
                # Chrome's History database is locked while Chrome is open
                # Copy to temp file to avoid locking issues
                with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
                    tmp_path = tmp.name
                    copy2(str(history_db), tmp_path)

                try:
                    conn = sqlite3.connect(tmp_path, timeout=5)
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()

                    # Chrome stores time as microseconds since 1601-01-01
                    # Convert our Unix timestamp to Chrome's format
                    chrome_since = (since_timestamp + 11644473600) * 1000000

                    # Fetch visits
                    if self.include_page_visits:
                        cursor.execute(
                            """
                            SELECT v.id, v.visit_time, u.url, u.title, v.visit_duration
                            FROM visits v
                            JOIN urls u ON v.url = u.id
                            WHERE v.visit_time > ? AND u.url NOT LIKE '%chrome://%'
                            ORDER BY v.visit_time DESC
                            LIMIT 500
                            """,
                            (chrome_since,),
                        )

                        for row in cursor.fetchall():
                            signal = self._parse_chrome_visit(
                                dict(row), profile_path.name
                            )
                            if signal:
                                signals.append(signal)

                    # Fetch searches (from search_terms table if available)
                    if self.include_searches:
                        try:
                            cursor.execute(
                                """
                                SELECT term, date_created
                                FROM search_terms
                                WHERE date_created > ?
                                ORDER BY date_created DESC
                                LIMIT 200
                                """,
                                (chrome_since,),
                            )

                            for row in cursor.fetchall():
                                signal = self._parse_chrome_search(
                                    row, profile_path.name
                                )
                                if signal:
                                    signals.append(signal)
                        except sqlite3.OperationalError:
                            # search_terms table may not exist
                            logger.debug(
                                "Chrome search_terms table not found in history"
                            )

                    conn.close()

                finally:
                    # Clean up temp file
                    try:
                        Path(tmp_path).unlink()
                    except Exception:
                        pass

            except Exception as e:
                logger.debug(f"Failed to read Chrome history from {profile_path}: {e}")

        return signals

    async def _fetch_firefox_history(self, since_timestamp: int) -> List[ActivitySignal]:
        """
        Fetch Firefox browsing history.

        Args:
            since_timestamp: Only return entries after this Unix timestamp

        Returns:
            List of ActivitySignal objects
        """
        signals = []
        firefox_paths = self._get_firefox_paths()

        for profile_path in firefox_paths:
            places_db = profile_path / "places.sqlite"
            if not places_db.exists():
                continue

            try:
                # Firefox's places.sqlite database can be locked
                # Copy to temp file to avoid locking issues
                with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
                    tmp_path = tmp.name
                    copy2(str(places_db), tmp_path)

                try:
                    conn = sqlite3.connect(tmp_path, timeout=5)
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()

                    # Firefox stores time as milliseconds since epoch
                    firefox_since = since_timestamp * 1000

                    # Fetch page visits
                    if self.include_page_visits:
                        cursor.execute(
                            """
                            SELECT h.id, h.visit_date, p.url, p.title
                            FROM moz_historyvisits h
                            JOIN moz_places p ON h.place_id = p.id
                            WHERE h.visit_date > ? AND p.url NOT LIKE 'about:%'
                            ORDER BY h.visit_date DESC
                            LIMIT 500
                            """,
                            (firefox_since,),
                        )

                        for row in cursor.fetchall():
                            signal = self._parse_firefox_visit(
                                dict(row), profile_path.name
                            )
                            if signal:
                                signals.append(signal)

                    conn.close()

                finally:
                    # Clean up temp file
                    try:
                        Path(tmp_path).unlink()
                    except Exception:
                        pass

            except Exception as e:
                logger.debug(f"Failed to read Firefox history from {profile_path}: {e}")

        return signals

    def _get_chrome_paths(self) -> List[Path]:
        """
        Get Chrome profile paths for current OS.

        Returns:
            List of profile directory paths
        """
        paths = []
        import platform

        if platform.system() == "Windows":
            base = Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data"
        elif platform.system() == "Darwin":  # macOS
            base = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
        elif platform.system() == "Linux":
            base = Path.home() / ".config" / "google-chrome"
        else:
            return paths

        if base.exists():
            # Chrome typically has "Default" and numbered profiles
            for profile_dir in base.glob("Profile *"):
                if profile_dir.is_dir():
                    paths.append(profile_dir)
            # Also check default profile
            default = base / "Default"
            if default.exists():
                paths.append(default)

        return paths

    def _get_firefox_paths(self) -> List[Path]:
        """
        Get Firefox profile paths for current OS.

        Returns:
            List of profile directory paths
        """
        paths = []
        import platform

        if platform.system() == "Windows":
            base = Path.home() / "AppData" / "Roaming" / "Mozilla" / "Firefox" / "Profiles"
        elif platform.system() == "Darwin":  # macOS
            base = (
                Path.home()
                / "Library"
                / "Application Support"
                / "Firefox"
                / "Profiles"
            )
        elif platform.system() == "Linux":
            base = Path.home() / ".mozilla" / "firefox"
        else:
            return paths

        if base.exists():
            for profile_dir in base.glob("*.default*"):
                if profile_dir.is_dir():
                    paths.append(profile_dir)

        return paths

    def _parse_chrome_visit(
        self, row: Dict[str, Any], profile_name: str
    ) -> Optional[ActivitySignal]:
        """
        Parse a Chrome visit record into an ActivitySignal.

        Args:
            row: Database row from Chrome history
            profile_name: Chrome profile name

        Returns:
            ActivitySignal or None
        """
        try:
            # Chrome stores time as microseconds since 1601-01-01
            chrome_timestamp = row.get("visit_time", 0)
            if chrome_timestamp == 0:
                return None

            # Convert to Unix timestamp
            timestamp = datetime.fromtimestamp(
                (chrome_timestamp / 1000000) - 11644473600
            )

            url = row.get("url", "")
            title = row.get("title", "") or url
            visit_duration = row.get("visit_duration", 0) // 1000000  # Convert to seconds

            # Extract domain from URL
            try:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc
            except Exception:
                domain = "unknown"

            description = f"Chrome: visited {title[:50]}"

            return ActivitySignal(
                source="browser",
                event_type="page_visit",
                timestamp=timestamp,
                data={
                    "url": url,
                    "title": title,
                    "domain": domain,
                    "browser": "chrome",
                    "profile": profile_name,
                    "time_spent_seconds": visit_duration,
                },
                description=description,
            )

        except Exception as e:
            logger.debug(f"Failed to parse Chrome visit: {e}")
            return None

    def _parse_chrome_search(
        self, row: tuple, profile_name: str
    ) -> Optional[ActivitySignal]:
        """
        Parse a Chrome search record into an ActivitySignal.

        Args:
            row: Database row from Chrome search_terms
            profile_name: Chrome profile name

        Returns:
            ActivitySignal or None
        """
        try:
            term = row[0]
            date_created = row[1]

            if not term or not date_created:
                return None

            # Chrome search_terms table stores time as microseconds since 1601-01-01
            timestamp = datetime.fromtimestamp(
                (date_created / 1000000) - 11644473600
            )

            description = f"Chrome search: {term[:50]}"

            return ActivitySignal(
                source="browser",
                event_type="search",
                timestamp=timestamp,
                data={
                    "query": term,
                    "engine": "google",  # Chrome typically uses Google
                    "browser": "chrome",
                    "profile": profile_name,
                },
                description=description,
            )

        except Exception as e:
            logger.debug(f"Failed to parse Chrome search: {e}")
            return None

    def _parse_firefox_visit(
        self, row: Dict[str, Any], profile_name: str
    ) -> Optional[ActivitySignal]:
        """
        Parse a Firefox visit record into an ActivitySignal.

        Args:
            row: Database row from Firefox places
            profile_name: Firefox profile name

        Returns:
            ActivitySignal or None
        """
        try:
            # Firefox stores time as milliseconds since epoch
            visit_time_ms = row.get("visit_date", 0)
            if visit_time_ms == 0:
                return None

            timestamp = datetime.fromtimestamp(visit_time_ms / 1000)

            url = row.get("url", "")
            title = row.get("title", "") or url

            if not url:
                return None

            # Extract domain from URL
            try:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc
            except Exception:
                domain = "unknown"

            description = f"Firefox: visited {title[:50]}"

            return ActivitySignal(
                source="browser",
                event_type="page_visit",
                timestamp=timestamp,
                data={
                    "url": url,
                    "title": title,
                    "domain": domain,
                    "browser": "firefox",
                    "profile": profile_name,
                    "time_spent_seconds": 0,  # Firefox doesn't track visit duration
                },
                description=description,
            )

        except Exception as e:
            logger.debug(f"Failed to parse Firefox visit: {e}")
            return None
