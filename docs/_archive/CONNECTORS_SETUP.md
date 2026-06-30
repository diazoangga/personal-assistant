# Enable Browser & Slack Connectors

Two new connectors are ready to monitor your activity:

## Browser Connector ✓ No credentials needed

**What it does:** Tracks your searches and web browsing (Google, GitHub, ArXiv, etc.)

### Enable it
1. Edit `config/settings.toml`:
```toml
[connectors.browser]
enabled = true                    # Change from false to true
browsers = ["chrome", "firefox"]  # Your browsers
track_searches = true
track_page_visits = true
min_time_on_page = 2              # Pages with 2+ seconds only
exclude_domains = ["localhost"]   # Skip these
```

2. Start daemon:
```bash
pa daemon start
```

3. Watch the logs:
```bash
pa daemon logs -f
```

You'll see:
```
[INFO] Got 12 signals from browser
- You searched for "transformer models"
- You visited arxiv.org (8 mins) - Attention is All You Need
- You visited github.com (3 mins) - anthropics/claude-code
```

**How it works:** Reads SQLite database files directly from your Chrome/Firefox installation. Completely local - no data leaves your machine.

---

## Slack Connector ✓ Needs token

**What it does:** Monitors messages in your Slack workspace and DMs

### Setup (3 steps)

**Step 1: Create Slack App**
- Visit https://api.slack.com/apps
- Click "Create New App"
- Choose "From scratch"
- Name: "Personal Assistant"
- Pick your workspace

**Step 2: Configure Scopes**
- Go to "OAuth & Permissions"
- Under "Bot Token Scopes" add:
  - `channels:history`
  - `groups:history`
  - `im:history`
  - `mpim:history`
  - `reactions:read`
- Scroll up and click "Install to Workspace"

**Step 3: Add Token to Config**
- Copy the "Bot Token" (starts with `xoxb-`)
- Edit `.env`:
```
SLACK_BOT_TOKEN=xoxb_your_token_here
```
- Edit `config/settings.toml`:
```toml
[connectors.slack]
enabled = true
slack_token = "${SLACK_BOT_TOKEN}"
channels = []                  # Empty = all channels you're in
include_dms = true
```

**Start daemon:**
```bash
pa daemon start
```

**View signals:**
```bash
pa daemon logs -f
```

You'll see:
```
[INFO] Got 8 signals from slack
- You messaged #general: "Great idea!"
- alice messaged you: "Thanks for the feedback"
- You reacted with :thumbsup: in #dev
```

---

## Test Both Together

```bash
# Make sure settings.toml has both enabled:
# [connectors.browser] enabled = true
# [connectors.slack] enabled = true

# Start daemon
pa daemon start

# In another terminal, watch logs
pa daemon logs -f
```

You should see combined signals from all enabled connectors:
```
[INFO] Starting ingest cycle...
[INFO] Got 5 signals from github
[INFO] Got 12 signals from browser
[INFO] Got 8 signals from slack
[INFO] Ingest cycle: 25 signals processed
```

---

## What's Next

Once signals are flowing:

1. **Signal integration** - Feed activity into the Interest Agent
2. **Classification** - Automatically detect your interests from activity patterns
3. **Research triggers** - Interest Agent automatically triggers Research Agent
4. **Recommendations** - Opportunity Agent proposes ideas based on your activity
5. **VSCode connector** - Track your coding activity (file edits, extensions, debugging)

---

## Troubleshooting

**Browser connector not working:**
- Make sure Chrome/Firefox is closed
- Check the database path exists (see CONNECTORS.md)
- Verify in logs: `pa daemon logs | grep browser`

**Slack connector not working:**
- Verify token: `echo $SLACK_BOT_TOKEN`
- Check app is installed to workspace
- Ensure you're a member of the channels you specified
- Try empty `channels = []` to monitor all channels

**Both showing zero signals:**
- Check daemon is actually running: `pa daemon status`
- Check logs: `pa daemon logs`
- Look for [ERROR] or [WARNING] entries

---

## Architecture

```
┌──────────────────────────────────┐
│     Daemon Main Loop (60s)       │
├──────────────────────────────────┤
│ Check:                           │
│  ├─ GitHub commits/PRs           │
│  ├─ Browser searches/visits      │
│  └─ Slack messages/reactions     │
│                                  │
└──────────────┬───────────────────┘
               │ Every 15 minutes
               ▼
    ┌──────────────────────┐
    │  Full Ingest Cycle   │
    └──────────┬───────────┘
               │
               ▼ Feed to Interest Agent
    ┌──────────────────────┐
    │ Interest Agent       │
    │ (Classify activity)  │
    └──────────┬───────────┘
               │
               ▼ Trigger on new interests
    ┌──────────────────────┐
    │ Research Agent       │
    │ (Look up papers)     │
    └──────────┬───────────┘
               │
               ▼ Synthesize
    ┌──────────────────────┐
    │ Opportunity Agent    │
    │ (Propose ideas)      │
    └──────────────────────┘
```

This is the flow! Right now we have signals. Next: Interest integration.
