# GitHub Connector

Fetches the user's GitHub activity (commits, PRs, issues) and emits `ActivitySignal`s.
**Enabled by default** (`[connectors.github]`).

## Config

| Key | Source | Notes |
|---|---|---|
| `github_token` | `GITHUB_TOKEN` env / config | PAT for the GitHub API |
| `github_username` | config | whose events to poll |
| `enabled` | `[connectors.github].enabled` | default `true` |

If token or username is missing, `fetch` returns `[]` (no-op, not an error).

## What it does

`fetch(since)` calls `GET /users/{username}/events?per_page=30` (with `since` when given),
then `_parse_event` maps GitHub event types to signal `event_type`s:

| GitHub event | signal `event_type` |
|---|---|
| `PushEvent` | `commit` |
| `PullRequestEvent` | `pull_request` |
| `IssuesEvent` | `issue` |
| `CreateEvent` | `create` |

Each signal carries `source="github"`, the event's `created_at` as `timestamp`, and a
`data` dict with the repository name and message/title — the fields
`InterestAgent._signal_to_text` reads for `github` signals.

## Gotchas

- The GitHub events API only returns recent public events; private activity needs an
  appropriately scoped token and may still be limited.
- Network/HTTP errors are caught and logged; `fetch` degrades to whatever it collected.

---

> **Source of truth:** `src/daemon/connectors/github.py`. Contract:
> [connector-contract.md](connector-contract.md).
