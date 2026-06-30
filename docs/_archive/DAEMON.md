# Personal Assistant Daemon

The daemon is a background service that runs 24/7 to continuously monitor user activity across multiple sources and feed it into the Interest Agent.

## Quick Start

### Start the daemon in background
```bash
pa daemon start
```

### Check daemon status
```bash
pa daemon status
```

### View daemon logs
```bash
pa daemon logs           # Show last 50 lines
pa daemon logs -n 200   # Show last 200 lines
pa daemon logs -f       # Tail logs (Ctrl+C to stop)
```

### Stop the daemon
```bash
pa daemon stop          # Graceful shutdown (SIGTERM)
pa daemon stop --force  # Force kill (SIGKILL)
```

### Run daemon in foreground (for debugging)
```bash
pa daemon start --foreground
```

## Configuration

Edit `config/settings.toml` under the `[daemon]` section:

```toml
[daemon]
check_interval_seconds = 60       # How often to check for updates
ingest_interval_minutes = 15      # How often to run full ingest cycle
log_level = "INFO"                # Logging level: DEBUG, INFO, WARNING, ERROR
log_file = "./data/daemon.log"    # Where to write daemon logs
pid_file = "./data/daemon.pid"    # Where to store daemon PID
```

## How It Works

The daemon runs in a loop:

1. **Check interval** (60s default): Connectors check for real-time updates (Slack messages, new tabs, etc.)
2. **Ingest interval** (15m default): Full cycle fetches all activity from all connectors since last check
3. **Activity signals** are sent to the Interest Agent for classification
4. **Interest classifications** trigger the Research Agent (if configured)
5. **Logs** are written to `./data/daemon.log`

```
┌─────────────────────────────────────┐
│  Daemon Main Loop (every 60s)       │
└────────┬────────────────────────────┘
         │
         ├─► Check connectors for realtime updates
         │   (Slack, browser tabs, etc.)
         │
         └─► If 15m elapsed since last ingest:
             │
             ├─► Fetch from GitHub connector
             ├─► Fetch from Browser connector
             ├─► Fetch from Slack connector
             ├─► ... (all enabled connectors)
             │
             └─► Feed signals to Interest Agent
                 │
                 └─► Interest classifications
                     └─► Trigger Research Agent (if needed)
```

## Adding New Connectors

A connector is a plugin that fetches activity from a source (VSCode, browser, files, Slack, etc.).

### Step 1: Create connector class

```python
# src/daemon/connectors/myconnector.py

from datetime import datetime
from typing import Any, Dict, List, Optional

from ..connector_base import ActivityConnector, ActivitySignal


class MyConnector(ActivityConnector):
    """Fetch activity from My Source."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.name = "mysource"
        # Initialize your connector

    async def fetch(self, since: Optional[datetime] = None) -> List[ActivitySignal]:
        """
        Fetch activity signals.
        
        Args:
            since: Only return signals after this timestamp (for efficiency)
        
        Returns:
            List of ActivitySignal objects
        """
        signals = []
        
        # Fetch data from your source
        # ...
        
        # Create ActivitySignal objects
        signal = ActivitySignal(
            source="mysource",
            event_type="file_changed",
            timestamp=datetime.now(),
            data={
                "file": "/path/to/file.py",
                "change": "modified",
            },
            description="You modified /path/to/file.py"
        )
        signals.append(signal)
        
        return signals

    async def initialize(self) -> None:
        """Optional: Setup (authenticate, connect, etc.)."""
        pass

    async def shutdown(self) -> None:
        """Optional: Cleanup."""
        pass
```

### Step 2: Register the connector

In `src/daemon/connectors/__init__.py`:

```python
from .myconnector import MyConnector

__all__ = ["MyConnector"]
```

In your CLI or main code:

```python
from src.daemon.connectors import MyConnector
from src.daemon.connector_base import register_connector

# Create and register
config = {"enabled": True, "option1": "value1"}
connector = MyConnector(config)
register_connector(connector)
```

Or automatically in the daemon startup:

```python
# In PersonalAssistantDaemon.initialize()
from src.daemon.connectors import MyConnector

if config.get("connectors", {}).get("mysource", {}).get("enabled"):
    connector = MyConnector(config.get("connectors", {}).get("mysource", {}))
    register_connector(connector)
```

### Step 3: Configure in settings.toml

```toml
[connectors.mysource]
enabled = true
option1 = "value1"
option2 = "value2"
```

## Built-in Connectors

### GitHub ✓
Fetches commits, PRs, issues, and comments.

```toml
[connectors.github]
enabled = true
github_token = "${GITHUB_TOKEN}"  # From .env
github_username = "your-username"
```

Signals:
- `commit` - Pushed commits
- `pull_request` - PR opened/closed/merged
- `issue` - Issue opened/closed/reopened
- `comment` - Comments on issues/PRs

**Example signals:**
```python
source="github", event_type="commit", data={"repo": "my-project", "message": "Fix bug", "files": 3}
source="github", event_type="pull_request", data={"repo": "my-project", "action": "opened", "title": "Add feature"}
```

### Browser ✓
Monitors web search queries and visited pages with time spent.

```toml
[connectors.browser]
enabled = false
browsers = ["chrome", "firefox"]  # Which browsers to monitor
track_searches = true             # Track search queries
track_page_visits = true          # Track visited pages
min_time_on_page = 2              # Only track pages with 2+ seconds
exclude_domains = [               # Don't track localhost, etc.
    "localhost",
    "127.0.0.1",
]
```

Signals:
- `search` - Search queries (Google, Bing, DuckDuckGo, etc.)
- `page_visit` - Pages visited with time spent

**Example signals:**
```python
source="browser", event_type="search", data={"query": "transformer models", "engine": "google"}
source="browser", event_type="page_visit", data={"url": "https://arxiv.org/...", "title": "Paper", "domain": "arxiv.org", "time_spent_seconds": 45}
```

**How it works:**
- Reads SQLite history databases directly from Chrome/Firefox
- Safely copies database files to avoid locking issues
- Converts timestamps correctly
- Filters by domain and time thresholds
- Works on Windows & macOS

**Browser history locations:**
- **Chrome (Windows)**: `~\AppData\Local\Google\Chrome\User Data\Default\History`
- **Chrome (macOS)**: `~/Library/Application Support/Google/Chrome/Default/History`
- **Firefox (Windows)**: `~\AppData\Roaming\Mozilla\Firefox\Profiles\*.default-release\places.sqlite`
- **Firefox (macOS)**: `~/Library/Application Support/Firefox/Profiles/*.default-release/places.sqlite`

### Slack ✓
Monitors messages in joined channels and direct messages.

```toml
[connectors.slack]
enabled = false                   # Set to true to enable
slack_token = "${SLACK_BOT_TOKEN}"  # From .env
channels = []                     # Empty = all joined channels, or ["#general", "#dev"]
include_dms = true                # Also monitor direct messages
```

Signals:
- `message` - Channel messages and DMs
- `reaction` - Emoji reactions
- `thread_reply` - Replies in threads

**Example signals:**
```python
source="slack", event_type="message", data={"channel": "#general", "user": "diazangga", "text": "Great idea!", "thread": False}
source="slack", event_type="message", data={"channel": "@alice", "user": "alice", "text": "Thanks!", "is_dm": True}
source="slack", event_type="reaction", data={"channel": "#dev", "emoji": "thumbsup", "message_text": "..."}
```

**Setup:**
1. Create a Slack app at https://api.slack.com/apps
2. Enable these scopes: `channels:history`, `groups:history`, `im:history`, `mpim:history`, `reactions:read`
3. Install the app to your workspace
4. Copy the Bot Token (starts with `xoxb-`)
5. Add to `.env`: `SLACK_BOT_TOKEN=xoxb-...`
6. Enable in settings.toml: `[connectors.slack] enabled = true`

### VSCode (TODO)
Fetches file edits, extensions used, debugging sessions.

```toml
[connectors.vscode]
enabled = false
workspace_path = "~/projects"
```

### File System (TODO)
Monitors file changes in specified directories.

```toml
[connectors.filesystem]
enabled = false
watch_paths = ["~/projects", "~/documents"]
```

## ActivitySignal Data Model

Every activity is represented as an `ActivitySignal`:

```python
@dataclass
class ActivitySignal:
    source: str                  # "github", "vscode", "browser", etc.
    event_type: str             # "commit", "file_changed", "search", etc.
    timestamp: datetime         # When it happened
    data: Dict[str, Any]        # Event-specific details
    user_id: Optional[str]      # Who did it (useful for multi-user)
    description: str            # Human-readable summary
```

Examples:

```python
# GitHub commit
ActivitySignal(
    source="github",
    event_type="commit",
    timestamp=datetime.now(),
    data={"repo": "my-project", "message": "Fix bug", "files": 3},
    user_id="my-username",
    description="You committed 3 files to my-project"
)

# File edit
ActivitySignal(
    source="vscode",
    event_type="file_changed",
    timestamp=datetime.now(),
    data={"file": "/path/to/file.py", "lines_added": 10, "lines_deleted": 5},
    description="You edited /path/to/file.py (+10, -5)"
)

# Web search
ActivitySignal(
    source="browser",
    event_type="search",
    timestamp=datetime.now(),
    data={"query": "transformer models", "engine": "google"},
    description="You searched for 'transformer models'"
)
```

## Troubleshooting

### Daemon won't start
1. Check logs: `pa daemon logs`
2. Try running in foreground: `pa daemon start --foreground`
3. Check OpenRouter API key: `pa config status`
4. Check file permissions on `./data/` directory

### High memory/CPU usage
1. Reduce `check_interval_seconds` or `ingest_interval_minutes`
2. Disable unused connectors in config
3. Check daemon logs for errors: `pa daemon logs -f`

### Missing activity
1. Verify connectors are enabled in `settings.toml`
2. Check API keys/credentials (.env file)
3. Review daemon logs: `pa daemon logs -n 500`

## Architecture

```
PersonalAssistantDaemon
├── PersonalAssistantEngine
│   ├── OpenRouterRuntime (LLM)
│   ├── KnowledgeBase (Qdrant vectors)
│   └── UserMemory (SQLite)
├── ActivityConnectors
│   ├── GitHubConnector
│   ├── BrowserConnector (TODO)
│   ├── VSCodeConnector (TODO)
│   ├── SlackConnector (TODO)
│   └── FileSystemConnector (TODO)
└── Main Loop
    ├── Check connectors (every 60s)
    └── Full ingest cycle (every 15m)
        └── Feed to Interest Agent
            └── Trigger Research Agent (if needed)
```

## Next Steps

After the daemon is running stably:

1. **Add VSCode connector** - Monitor file edits and extensions
2. **Add Browser connector** - Track web search and browsing
3. **Add Slack connector** - Monitor messages and reactions
4. **Implement signal → Interest model** - Feed activity to the Interest Agent
5. **Cross-source analysis** - Correlate activities across sources
6. **Proactive insights** - Generate recommendations from accumulated data
