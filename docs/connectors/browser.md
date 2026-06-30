# Browser Connector

Reads local browser history (Chrome/Firefox) and emits `search` and `page_visit` signals.
**Disabled by default** (`[connectors.browser].enabled = false`) — it touches local history
databases, so it's opt-in.

## Config

```toml
[connectors.browser]
enabled = false
browsers = ["chrome", "firefox"]
track_searches = true
track_page_visits = true
min_time_on_page = 2          # seconds; ignore quick bounces
exclude_domains = ["localhost", "127.0.0.1"]
```

## What it does

`fetch(since)` reads the configured browsers' history stores and emits:

| `event_type` | `data` fields used by the classifier |
|---|---|
| `search` | `query`, `engine` |
| `page_visit` | `domain`, `title` |

Signals carry `source="browser"` and the visit's real timestamp. `exclude_domains` and
`min_time_on_page` filter noise before signals are produced.

## Gotchas

- Browser history files are often **locked while the browser is running**; reads may need a
  copy-then-read or may skip locked stores.
- This is the most privacy-sensitive connector — it sees everything the user browses. Keep
  it off unless the user explicitly opts in, and honour `exclude_domains`.

---

> **Source of truth:** `src/daemon/connectors/browser.py`. Contract:
> [connector-contract.md](connector-contract.md).
