---
title: "Implementation: Slack Gateway"
created: 2026-06-20
updated: 2026-06-21
version: 3.0.0
status: Draft
tags: [implementation, slack, gateway]
changelog:
  - version: 1.0.0
    date: 2026-06-20
    changes: "Initial Slack adapter for the SDLC builder (/build, approvals)"
  - version: 2.0.0
    date: 2026-06-21
    changes: >-
      Updated for the cognitive engine. Replaced /build + approval buttons with
      /ask, /brainstorm threads, /interests, /digest, /opps and feedback (👍/👎)
      buttons; reframed the digest as the proactive insight digest. Socket Mode
      and the 3-second async pattern retained.
  - version: 3.0.0
    date: 2026-06-21
    changes: >-
      Added `/research` (manual Research Agent trigger) and `/graph` (citation
      /knowledge graph view) slash commands. Brainstorm thread sessions now run
      the Brainstorming Agent (a full agent) rather than a Meta Agent mode, and
      can post a "researching…" progress update if the session hands off to the
      Research Agent mid-conversation. Repointed the digest producer reference
      to the Opportunity Agent (impl/05), and added a self-modification review
      surface (`/review`) for Meta Agent proposals (D6).
related:
  - ../personal-assistant.plans.md
  - 01-cli-and-core-engine.md
reference:
  - https://docs.slack.dev/ai/
  - https://tools.slack.dev/bolt-python/
---

> Whenever this documentation file changes, update the `updated` field and append a new entry to `changelog` describing the revision.

# Implementation: Slack Gateway

Slack is the second symmetric adapter (D2). It builds the same `Command` objects as
the CLI and renders the same `Event` stream — only the presentation (Block Kit) and
the async/ack mechanics differ. If you find yourself writing agent or storage logic
here, it belongs in the Core Engine.

---

## 1. Connection Mode: Socket Mode

Use **Socket Mode** (WebSocket), not a public HTTP endpoint.

| | Socket Mode | Events API (HTTP) |
|---|---|---|
| Public URL | not required | required (tunnel + TLS) |
| Fit for | a single local box | multi-instance, load-balanced |
| Setup | app-level token, outbound WS | request URL verification, inbound |

For a solo, local-first assistant, Socket Mode is the right call: no inbound firewall
holes, no tunnel.

```python
# src/adapters/slack/app.py
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from pa.core import build_engine
from pa.core.commands import Ask, Brainstorm, ShowInterests, Opportunities, ShowDigest, Feedback

app = AsyncApp(token=BOT_TOKEN)
engine = build_engine()
```

---

## 2. The 3-Second Rule (the core async pattern)

Slack requires `ack()` within **3 seconds**. Agent work takes longer. So: **ack
immediately, then stream results asynchronously.**

```python
@app.command("/ask")
async def handle_ask(ack, command, respond):
    await ack("🔎 searching your knowledge base…")        # < 3s, mandatory
    cmd = Ask(user=command["user_id"], query=command["text"])
    job_id = await engine.submit(cmd)                      # returns instantly
    async for ev in engine.events(job_id):
        await render_to_slack(ev, respond, command["channel_id"])
        if isinstance(ev, Result): break
```

> Never do agent work inside the handler before `ack()`. Ack first, always.

---

## 3. Brainstorm in a Thread (one thread = one session)

The flagship interaction. A `/brainstorm` opens a thread; every reply in that thread
becomes a `Brainstorm(text, session_id=thread_ts)` command, and the engine streams
`Message` turns back into the thread.

```python
@app.command("/brainstorm")
async def start_brainstorm(ack, command, client):
    await ack()
    root = await client.chat_postMessage(channel=command["channel_id"],
                                         text="🧠 Brainstorm started — reply in this thread.")
    # remember root["ts"] as the session id for this thread

@app.event("message")
async def on_thread_reply(event, say):
    if not event.get("thread_ts"):                         # only in-thread replies
        return
    cmd = Brainstorm(user=event["user"], text=event["text"], session_id=event["thread_ts"])
    job_id = await engine.submit(cmd)
    async for ev in engine.events(job_id):
        if isinstance(ev, Message):
            await say(thread_ts=event["thread_ts"], blocks=message_blocks(ev))   # text + citations
        if isinstance(ev, Result): break
```

Inquiry turns come back strict + cited; ideation turns come back as proposals with
"why this" provenance. A "💾 Save idea" button on a proposal submits an
`Opportunities(action="save", ref=…)` command.

The Brainstorming Agent can decide, mid-session, that KB coverage is too thin and
submit a `ResearchTopic` command itself ("research this, then propose"). When it
does, the thread sees an interstitial progress message ("🔎 researching `<topic>`
— this may take a minute…") before the ideation turn arrives, so the latency jump
from a normal KB-only turn is visible rather than a silent stall.

---

## 4. Rendering the Event Stream (Block Kit)

The Slack twin of the CLI's `render()` table. Same events, different paint.

| Event | Slack rendering |
|-------|-----------------|
| `Started` | message: "job `<id>` started" (+ Cancel button) |
| `Progress` | `chat.update` the message: phase + message |
| `Message` | assistant text + a "Sources" context block listing `citations` |
| `Result(ok=True)` | summary section (e.g. opportunity list with 👍/👎 + 💾 buttons) |
| `Result(ok=False)` | error + "view log: `/status <job>`" |

---

## 5. Feedback Buttons (the learning loop)

Recommendations and answers carry 👍/👎 (and 💾 Save / 🗑 Dismiss for opportunities).
Each button just emits a `Feedback` or `Opportunities` command — the same the CLI
sends — so the Meta Agent's performance tracking gets the signal regardless of
interface.

```python
@app.action("fb_accept")
async def on_accept(ack, body):
    await ack()
    ref = body["actions"][0]["value"]
    await engine.submit(Feedback(user=body["user"]["id"], ref=ref, verdict="accept"))
```

---

## 6. The Insight Digest Delivery

The insight digest is *outbound* and posts to `#assistant`. It is produced by the
**Opportunity Agent**, synthesizing across the Research Agent's findings and the
Interest Agent's model (see
[05-meta-agent-and-skills.md §5](05-meta-agent-and-skills.md#5-the-opportunity-agent-the-value-producer));
the Slack adapter only provides a `post_digest(blocks)` sink.

```python
async def post_digest(blocks: list[dict]):
    await app.client.chat_postMessage(channel=DIGEST_CHANNEL, blocks=blocks)
```

Layout: a header, one section per top interest (3–4 ranked items: title, source,
one-line "why it matters"), an "Adjacent — worth a look" serendipity section, and a
footer hint to `/ask` or `/brainstorm`.

---

## 7. Slack App Manifest (scopes & commands)

```yaml
display_information:
  name: Personal Assistant
features:
  bot_user: { display_name: pa }
  slash_commands:
    - { command: /ask,        description: "Ask your knowledge base", usage_hint: "<question>" }
    - { command: /brainstorm, description: "Start a brainstorm thread (KB + web search)" }
    - { command: /interests,  description: "Show your interest model", usage_hint: "[timeline]" }
    - { command: /research,   description: "Trigger the Research Agent for a topic", usage_hint: "<topic> [depth]" }
    - { command: /graph,      description: "Show the citation/knowledge graph", usage_hint: "[knowledge|citation] [topic]" }
    - { command: /digest,     description: "Show the latest insight digest" }
    - { command: /opps,       description: "List/save/dismiss opportunities", usage_hint: "list|save|dismiss" }
    - { command: /ingest,     description: "Run activity sensing now", usage_hint: "[connector]" }
    - { command: /review,     description: "List/approve/reject Meta Agent self-modification proposals (D6)", usage_hint: "list|approve|reject <id>" }
    - { command: /status,     description: "Job status", usage_hint: "[job]" }
    - { command: /prefs,      description: "Manage preferences", usage_hint: "set <k> <v>" }
    - { command: /topics,     description: "Manage tracked topics", usage_hint: "add|list|rm" }
    - { command: /sources,    description: "Manage connectors", usage_hint: "add|list|rm" }
oauth_config:
  scopes:
    bot: [commands, chat:write, chat:write.public, channels:history, groups:history]
settings:
  socket_mode_enabled: true
  interactivity: { is_enabled: true }
  event_subscriptions:
    bot_events: [message.channels, message.groups]    # for brainstorm thread replies
```

> `channels:history` / `message.*` are needed for the brainstorm-thread pattern. If
> you skip threaded brainstorm initially, drop them. Tokens: a **bot token**
> (`xoxb-…`) and an **app-level token** (`xapp-…`, `connections:write`) in `.env`;
> never commit.

---

## 8. Parity & Testing

- **Parity:** every slash command maps to a `Command` the CLI also exposes — the
  parity test in [01](01-cli-and-core-engine.md) §6 enforces it.
- **Ack-timing test:** assert `ack()` fires before `engine.submit()` completes work
  (mock a slow engine).
- **Renderer test:** feed a canned event stream to `render_to_slack` and snapshot the
  Block Kit JSON (incl. a `Message` turn with citations).

---

## Related
- [01-cli-and-core-engine.md](01-cli-and-core-engine.md) — the contracts this adapter renders
- [05-meta-agent-and-skills.md](05-meta-agent-and-skills.md) — digest producer (Opportunity Agent); D6 review workflow behind `/review`
- [06-research-agent.md](06-research-agent.md) — what `/research` triggers
- [../personal-assistant.brainstorm-feature.md](../personal-assistant.brainstorm-feature.md) — Brainstorm design
- [../personal-assistant.implementation.md](../personal-assistant.implementation.md)
