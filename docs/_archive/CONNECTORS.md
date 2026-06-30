# Activity Connectors Guide

Connectors feed activity data from different sources into the daemon. Each connector translates events from its source into standardized `ActivitySignal` objects.

## Quick Start

1. **Enable a connector** in `config/settings.toml`
2. **Configure credentials** in `.env`
3. **Start the daemon**: `pa daemon start`
4. **Monitor signals**: `pa daemon logs -f`

## GitHub Connector ✓ WORKING

Fetches your GitHub activity: commits, PRs, issues, comments.

### Setup
```toml
[connectors.github]
enabled = true
github_token = "${GITHUB_TOKEN}"
github_username = "your-github-username"
```

### Get GitHub Token
1. Visit https://github.com/settings/tokens/new
2. Create a token with scope `public_repo` (or `repo` for private repos)
3. Add to `.env`: `GITHUB_TOKEN=ghp_...`

### What it tracks
- **Commits**: When you push code
- **Pull Requests**: When you create/update/merge PRs
- **Issues**: When you create/comment on issues
- **Reviews**: When you review pull requests

### Example signals in logs
```
[INFO] Got 5 signals from github
- You committed 3 files to my-project
- You opened PR on my-project: Add feature
- You starred awesome-library
```

## Browser Connector ✓ READY (disabled by default)

Monitors your web searches and browsing history. Reads directly from your browser's SQLite databases.

### Setup
```toml
[connectors.browser]
enabled = true
browsers = ["chrome", "firefox"]
track_searches = true
track_page_visits = true
min_time_on_page = 2              # Only track pages with 2+ seconds
exclude_domains = [
    "localhost",
    "127.0.0.1",
    "reddit.com",                 # Optional: skip time-wasting sites
]
```

### How it works
1. Locates browser history files (automatic, per OS)
2. Copies to temp file (to avoid locking issues)
3. Queries SQLite database for recent entries
4. Filters by time threshold and excluded domains
5. Converts timestamps and returns `ActivitySignal` objects

**No credentials needed** - reads local files directly.

### What it tracks
- **Searches**: Google, Bing, DuckDuckGo, etc. queries
- **Page visits**: URLs visited, with title and time spent
- **Domains**: Aggregates by domain (arxiv.org, github.com, etc.)

### Example signals in logs
```
[INFO] Got 12 signals from browser
- You searched for "transformer models" on google
- You visited arxiv.org (8 mins 45 secs) - Attention is All You Need
- You visited github.com (3 mins 12 secs) - anthropics/claude-code
```

### Supported browsers
- **Chrome/Chromium** (Windows, macOS, Linux)
- **Firefox** (Windows, macOS, Linux)
- **Safari** (macOS - via browser history export, not automatic)

### Database locations
**Chrome:**
- Windows: `%LOCALAPPDATA%\Google\Chrome\User Data\Default\History`
- macOS: `~/Library/Application Support/Google/Chrome/Default/History`
- Linux: `~/.config/google-chrome/Default/History`

**Firefox:**
- Windows: `%APPDATA%\Mozilla\Firefox\Profiles\*.default-release\places.sqlite`
- macOS: `~/Library/Application Support/Firefox/Profiles/*.default-release/places.sqlite`
- Linux: `~/.mozilla/firefox/*.default-release/places.sqlite`

## Slack Connector ✓ READY (disabled by default)

Monitors messages in your Slack workspace: channels, DMs, threads.

### Setup
```toml
[connectors.slack]
enabled = true
slack_token = "${SLACK_BOT_TOKEN}"
channels = []                     # Empty = all, or ["#general", "#dev"]
include_dms = true
```

### Get Slack Token
1. Create a Slack app at https://api.slack.com/apps
2. Go to OAuth & Permissions
3. Add these scopes:
   - `channels:history` - Read channel messages
   - `groups:history` - Read private channel messages  
   - `im:history` - Read DM messages
   - `mpim:history` - Read group DM messages
   - `reactions:read` - Read emoji reactions
4. Install app to workspace
5. Copy Bot Token (starts with `xoxb-`)
6. Add to `.env`: `SLACK_BOT_TOKEN=xoxb_...`

### What it tracks
- **Channel messages**: What you discuss in channels
- **Direct messages**: Conversations with individuals
- **Reactions**: Emoji reactions you make
- **Threads**: Replies in threads

### Example signals in logs
```
[INFO] Got 8 signals from slack
- You messaged #general: "Great idea!"
- You replied in thread: "Let's do it"
- You reacted with :thumbsup: in #dev
- alice messaged you: "Thanks!"
```

### Configuration options
```toml
[connectors.slack]
# Which channels to monitor (empty = all you're a member of)
channels = ["#general", "#dev", "#research"]

# Include direct messages
include_dms = true

# Optional: only fetch messages after N hours (default: since last run)
lookback_hours = 24
```

## VSCode Connector (TODO)

Will track:
- File edits with filenames and languages
- Extensions installed/used
- Debugging sessions and breakpoints
- Terminal commands executed
- Git operations within VSCode

**Coming soon**: Currently only local file monitoring. Will use VSCode extension or workspace tracking.

## File System Connector (TODO)

Will monitor:
- Document changes (Word, Markdown, PDFs)
- New file creation
- File deletions
- Directory structure changes

## Creating a Custom Connector

See the example implementations (GitHub, Slack, Browser) in `src/daemon/connectors/`.

### Template
```python
from datetime import datetime
from typing import Any, Dict, List, Optional
from ..connector_base import ActivityConnector, ActivitySignal

class MyConnector(ActivityConnector):
    """Fetch activity from My Source."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.name = "mysource"

    async def fetch(self, since: Optional[datetime] = None) -> List[ActivitySignal]:
        """
        Fetch activity since timestamp.
        
        Args:
            since: Only return events after this time
        
        Returns:
            List of ActivitySignal objects
        """
        signals = []
        
        # 1. Check if enabled
        if not self.enabled:
            return signals
        
        # 2. Fetch from your source
        try:
            events = await self._fetch_events(since)
        except Exception as e:
            logger.error(f"Error fetching events: {e}", exc_info=True)
            return signals
        
        # 3. Convert to ActivitySignal
        for event in events:
            signal = ActivitySignal(
                source="mysource",
                event_type="action",
                timestamp=event.timestamp,
                data={...},
                description="Human-readable summary"
            )
            signals.append(signal)
        
        return signals
```

### Register your connector
1. Place in `src/daemon/connectors/myconnector.py`
2. Export in `src/daemon/connectors/__init__.py`
3. Add to daemon initialization in `src/daemon/service.py`
4. Add config section to `settings.toml`

## Signal Data Models

Every activity becomes an `ActivitySignal`:

```python
@dataclass
class ActivitySignal:
    source: str              # "github", "slack", "browser", etc.
    event_type: str         # "commit", "message", "search", etc.
    timestamp: datetime     # When it happened
    data: Dict[str, Any]    # Event-specific details
    user_id: Optional[str]  # Who did it
    description: str        # Human-readable summary
```

### Common event types
- `commit` - Code committed
- `message` - Message sent
- `search` - Search query
- `page_visit` - Visited a page
- `pull_request` - PR activity
- `issue` - Issue activity
- `reaction` - Emoji reaction
- `file_changed` - File modified

## Monitoring Signals

### View in real-time
```bash
pa daemon logs -f
```

### Grep for specific source
```bash
pa daemon logs | grep "slack\|github\|browser"
```

### Count signals by source
```bash
pa daemon logs | grep "Got.*signals" | grep -o "[0-9]* signals"
```

## Troubleshooting

### "No signals from [connector]"
1. Check it's enabled in settings.toml
2. Check credentials in .env
3. Check logs for errors: `pa daemon logs`
4. Run connector test (coming soon)

### Browser connector not finding history
1. Make sure the browser is closed or not in exclusive mode
2. Check the database location is correct for your OS
3. Verify the path exists: `ls ~/Library/Application\ Support/Google/Chrome/Default/History` (macOS) or Windows equivalent
4. Try Firefox as fallback

### Slack connector not fetching messages
1. Verify token is correct: `echo $SLACK_BOT_TOKEN`
2. Check app is installed to workspace
3. Verify scopes include `channels:history`, `im:history`
4. Check channel list is correct
5. Ensure user is a member of specified channels

### High CPU/memory usage
1. Reduce check_interval in daemon config
2. Disable expensive connectors (browser reads entire history files)
3. Increase min_time_on_page threshold in browser config

## Next: Signal Integration

Once signals are flowing, they need to be fed into the **Interest Agent**:
- Activity classification (what topics are you interested in?)
- Strength scoring (how interested are you?)
- Automated research triggers
- Opportunity recommendations based on activity

This is the next major piece to implement!
