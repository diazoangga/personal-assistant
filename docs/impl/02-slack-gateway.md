---
title: "Implementation: Slack Gateway"
created: 2026-06-20
updated: 2026-06-20
version: 1.0.0
status: Draft
tags: [implementation, slack, gateway]
related:
  - ../personal-assistant.plans.md
  - 01-cli-and-core-engine.md
reference:
  - https://docs.slack.dev/ai/
  - https://tools.slack.dev/bolt-python/
---

> Whenever this documentation file changes, update the `updated` field and append a new entry to `changelog` describing the revision.

# Implementation: Slack Gateway

Slack is the second symmetric adapter (D2). It builds the exact same `Command`
objects as the CLI and renders the same `Event` stream — only the presentation
(Block Kit) and the async/ack mechanics differ. If you find yourself writing agent
or storage logic here, it belongs in the Core Engine instead.

---

## 1. Connection Mode: Socket Mode

Use **Socket Mode** (WebSocket), not a public HTTP endpoint.

| | Socket Mode | Events API (HTTP) |
|---|---|---|
| Public URL | not required | required (ngrok/host + TLS) |
| Fit for | a single local Linux box | multi-instance, load-balanced |
| Setup | app-level token, outbound WS | request URL verification, inbound |

For a solo, local-first assistant, Socket Mode is the right call: no inbound
firewall holes, no tunnel. (If this ever scales to multiple instances, switch to
the Events API — the adapter boundary makes that a localized change.)

```python
# pa/adapters/slack/app.py
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from pa.core import build_engine
from pa.core.commands import Build, Ask, JobStatus, Approve, ResearchNow

app = AsyncApp(token=BOT_TOKEN)
engine = build_engine()
```

---

## 2. The 3-Second Rule (the core async pattern)

Slack requires `ack()` within **3 seconds** or it shows the user an error. Agent
work takes much longer. So: **ack immediately, then stream results
asynchronously.** `response_url` is valid for ~30 minutes, which comfortably
covers a build.

```python
@app.command("/build")
async def handle_build(ack, command, respond):
    await ack(f"🛠️ Starting build…")                      # < 3s, mandatory
    cmd = Build(user=command["user_id"], idea=command["text"])
    job_id = await engine.submit(cmd)                      # returns instantly
    await respond(blocks=started_blocks(job_id))
    # stream the same Event stream the CLI renders, but as Block Kit updates
    async for ev in engine.events(job_id):
        await render_to_slack(ev, respond, command["channel_id"])
        if isinstance(ev, Result):
            break
```

```
/build ────► ack() in <3s ────► submit() ────► job_id
                                     │
                                     ▼
                       engine.events(job_id) stream
                                     │
              Progress ──► update message via respond()/chat.update
              ApprovalNeeded ──► post Approve/Reject buttons
              Result ──► final summary + repo link
```

> Never do agent work inside the slash-command handler before `ack()`. Ack first,
> always.

---

## 3. Rendering the Event Stream (Block Kit)

This is the Slack twin of the CLI's `render()` table. Same events, different paint.

| Event | Slack rendering |
|-------|-----------------|
| `Started` | message: "job `<id>` started" with a Cancel button |
| `Progress` | `chat.update` the original message: phase + message (+ progress emoji) |
| `ApprovalNeeded` | Block Kit section with the `preview` + **Approve** / **Reject** buttons |
| `Result(ok=True)` | summary section + repo/path link + "open report" overflow |
| `Result(ok=False)` | error section + "view log: `/status <job>`" |

To keep one tidy message instead of a noisy thread, store the `ts` of the first
posted message per `job_id` and `chat.update` it on each `Progress`.

---

## 4. Interactive Approvals (HITL gate)

The gate that the engine parks on (see
[01-cli-and-core-engine.md](01-cli-and-core-engine.md) §3) surfaces in Slack as
buttons. The button action just emits the same `Approve`/`Cancel` command.

```python
@app.action("approve_job")
async def on_approve(ack, body, respond):
    await ack()
    job_id = body["actions"][0]["value"]
    await engine.submit(Approve(user=body["user"]["id"], job_id=job_id))
    await respond(replace_original=True, text="✅ Approved — continuing.")
```

Because both the button and `pa approve` produce an `Approve` command, a gate
opened in Slack can be cleared from the CLI and vice-versa.

---

## 5. The Daily Digest Delivery

Loop 1's digest is *outbound* and posts to `#daily-intelligence`. It is produced by
the Core Engine's research loop (see
[04-daily-research-agent.md](04-daily-research-agent.md)); the Slack adapter only
provides a `post_digest(blocks)` sink.

```python
async def post_digest(blocks: list[dict]):
    await app.client.chat_postMessage(channel=DIGEST_CHANNEL, blocks=blocks)
```

Digest Block Kit layout: a header, then one section per topic classification with
3–5 ranked items (title, source, one-line "why it matters", link), and a footer
with an `/ask` hint to dig deeper into anything ingested today.

---

## 6. Slack App Manifest (scopes & commands)

Create the app from a manifest so it's reproducible. Minimum scopes/commands:

```yaml
display_information:
  name: Personal Assistant
features:
  bot_user: { display_name: pa }
  slash_commands:
    - { command: /build,    description: "Run the SDLC pipeline", usage_hint: "<idea>" }
    - { command: /research, description: "Run research now" }
    - { command: /digest,   description: "Show the latest digest" }
    - { command: /ask,      description: "Query the knowledge base", usage_hint: "<question>" }
    - { command: /status,   description: "Job status", usage_hint: "[job]" }
    - { command: /approve,  description: "Approve a gate", usage_hint: "<job>" }
    - { command: /cancel,   description: "Cancel a job", usage_hint: "<job>" }
    - { command: /prefs,    description: "Manage preferences", usage_hint: "set <k> <v>" }
    - { command: /topics,   description: "Manage tracked topics", usage_hint: "add|list|rm" }
oauth_config:
  scopes:
    bot: [commands, chat:write, chat:write.public]
settings:
  socket_mode_enabled: true
  interactivity: { is_enabled: true }
```

Tokens needed: a **bot token** (`xoxb-…`) and an **app-level token** (`xapp-…`,
scope `connections:write`) for Socket Mode. Store both in `.env`; never commit.

---

## 7. Parity & Testing

- **Parity:** every slash command here must map to a `Command` that the CLI also
  exposes. The parity test in [01](01-cli-and-core-engine.md) §6 enforces it.
- **Ack-timing test:** assert the handler calls `ack()` before `engine.submit()`
  returns work (mock a slow engine; ack must still fire immediately).
- **Renderer test:** feed a canned event stream to `render_to_slack` and snapshot
  the Block Kit JSON.

---

## Related
- [01-cli-and-core-engine.md](01-cli-and-core-engine.md) — the contracts this adapter renders
- [04-daily-research-agent.md](04-daily-research-agent.md) — digest producer
- [../personal-assistant.implementation.md](../personal-assistant.implementation.md)
