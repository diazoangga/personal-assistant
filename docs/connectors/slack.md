# Slack Connector

Reads Slack messages from configured channels (and optionally DMs) and emits `message`
signals. **Disabled by default** (`[connectors.slack].enabled = false`).

## Config

```toml
[connectors.slack]
enabled = false
channels = ["#general"]
include_dms = true
```

Plus `SLACK_BOT_TOKEN` in the environment for API access.

## What it does

`fetch(since)` pulls messages newer than `since` from the configured channels and emits
signals with `source="slack"`, `event_type="message"`, and `data` carrying `channel` and
`text` — the fields `InterestAgent._signal_to_text` reads for slack signals (text is
truncated to ~100 chars for classification).

## Gotchas

- Requires a bot token with history scopes for the target channels; missing/under-scoped
  tokens yield no signals.
- DMs are sensitive — `include_dms` is opt-in and should be surfaced clearly to the user.

---

> **Source of truth:** `src/daemon/connectors/slack.py`. Contract:
> [connector-contract.md](connector-contract.md).
