---
title: "RFC: Telegram Mini App as Primary Gateway"
created: 2026-06-23
updated: 2026-06-23
version: 1.0.0
status: Draft
tags:
  - explanation
  - architecture
  - telegram
  - gateway
changelog:
  - version: 1.0.0
    date: 2026-06-23
    changes: "Initial RFC: Telegram Mini App as single primary gateway, replacing Slack as priority. Covers architecture, API design, phased implementation roadmap, and open questions."
audience: "Architecture team; decision-makers on frontend framework, hosting strategy, and auth scope"
related:
  - docs/impl/02-slack-gateway.md
  - docs/plans/personal-assistant.plans.md
  - docs/brainstorming-agent.plan.md
  - docs/research-agent.plan.md
reference:
  - https://core.telegram.org/bots/webapps
  - https://core.telegram.org/bots/api
  - https://github.com/aiogram/aiogram
  - https://github.com/python-telegram-bot/python-telegram-bot
---

> Whenever this documentation file changes, update the `updated` field and append a new entry to `changelog` describing the revision.

# RFC: Telegram Mini App as Primary Gateway

## Overview & Strategic Decision

**Decision:** Telegram Mini App is the sole primary user-facing gateway for Personal Assistant. All user interaction flows through either:
1. **Bot chat** — quick commands, notifications, entry points
2. **Mini App webview** — full-featured Q&A, brainstorming, research-graph visualization, settings

**Slack impact:** Slack gateway (documented in [02-slack-gateway.md](docs/impl/02-slack-gateway.md)) moves to the backlog. The Telegram Mini App inherits all Slack's command semantics and event-rendering patterns — the same `Command` and `Event` contracts — with only presentation changing.

**Why Telegram:**
- Single platform for chat + rich UI (Mini App webview)
- No plugin/scope negotiation; simpler deployment
- Mobile-first (browser-based on Telegram mobile = native app feel)
- Self-hosted bot backend (no Slack workspace overhead)
- First-class support for inline keyboards, interactive forms, and graphs

---

## 1. Architecture Overview

### Components

```
┌─────────────────────────────────────────────────────────────┐
│ Telegram Client (Mobile/Desktop)                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────┐         ┌──────────────────────┐     │
│  │  Bot Chat        │         │  Mini App Webview    │     │
│  │  (quick cmds)    │         │  (full interface)    │     │
│  │  /ask            │◄────────│  Chat / Brainstorm   │     │
│  │  /brainstorm     │         │  Research Graph      │     │
│  │  buttons         │         │  Settings            │     │
│  └────────┬─────────┘         └──────────┬───────────┘     │
│           │                              │                  │
└───────────┼──────────────────────────────┼──────────────────┘
            │ Bot API (long-poll/webhook)  │ TG WebApp API
            │                              │ (postMessage)
            │                              │
┌───────────▼──────────────────────────────▼──────────────────┐
│ Backend Service (single process)                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────┐                                   │
│  │  Bot Handler         │                                   │
│  │  (aiogram)           │                                   │
│  │  Route /ask, buttons │                                   │
│  └─────────┬────────────┘                                   │
│            │                                                │
│            └──────────┬──────────────────────────┐          │
│                       │                          │          │
│            ┌──────────▼─────────┐    ┌──────────▼────┐     │
│            │  Web API (FastAPI) │    │  Daemon Loop  │     │
│            │  REST endpoints    │    │  (signal flow)│     │
│            │  WebSocket stream  │    │  (unchanged)  │     │
│            └──────────┬─────────┘    └───────────────┘     │
│                       │                                      │
│            ┌──────────▼─────────────────────────────┐       │
│            │  Personal Assistant Engine             │       │
│            │  ├─ Command router                     │       │
│            │  ├─ EventBus (streaming results)       │       │
│            │  └─ Agents (Interest, Research, etc.)  │       │
│            └──────────┬─────────────────────────────┘       │
│                       │                                      │
│            ┌──────────▼─────────────────────────────┐       │
│            │  Storage (Unified Knowledge Store)     │       │
│            │  ├─ SQLite (knowledge.db)              │       │
│            │  ├─ Qdrant (vectors)                   │       │
│            └──────────────────────────────────────────┘     │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Service Architecture

**Single unified backend service** runs three components in parallel:

1. **Bot handler** — receives `/ask`, button presses, etc. via `aiogram` + long-poll/webhook
2. **Web API** — REST + WebSocket for Mini App
3. **Daemon loop** — periodic activity ingestion (unchanged from existing design)

All three share the same `PersonalAssistantEngine` instance and `EventBus`.

---

## 2. Bot Chat Surface (Telegram Bot API)

### Commands & Quick Actions

Bot chat is the **entry point and notification sink**. Commands mirror the Slack design:

| Command | Purpose | Response |
|---------|---------|----------|
| `/ask <query>` | Query knowledge base | Streamed answer with sources |
| `/brainstorm <topic>` | Launch brainstorm session | "Brainstorm started → open Mini App" |
| `/interests [filter]` | Show interest model | Card list (top 10) |
| `/research <topic> [depth]` | Trigger Research Agent | Progress updates |
| `/graph [kind] [topic]` | View citation/knowledge graph | "Open Mini App → Graph tab" |
| `/digest [date]` | Show insight digest | Formatted summary |
| `/opps` | Manage opportunities | List + action buttons |
| `/ingest [connector]` | Manual signal ingest | "Ingesting… → status" |
| `/prefs` | Manage settings | "Open Mini App → Settings" |
| `/topics` | Manage tracked topics | List + add/remove buttons |

### 3-Second Ack Pattern (Telegram Edition)

Telegram bots must respond to commands quickly. The pattern is identical to Slack:

```python
# src/adapters/telegram/bot_handler.py
@dp.message(Command("ask"))
async def handle_ask(message: Message):
    # Ack immediately with a placeholder
    status_msg = await message.answer("🔎 Searching…", parse_mode="HTML")
    
    # Build command and submit
    cmd = Ask(user=str(message.from_user.id), query=message.text)
    job_id = await engine.submit(cmd)
    
    # Stream results (async, outside the 3-sec window)
    async for event in engine.events(job_id):
        await render_event_to_telegram(event, message, status_msg)
```

**Response handling:**
- `Started` → update placeholder to "Searching…"
- `Progress` → edit message with phase + percentage
- `Message` → post assistant text + inline cite buttons
- `Result` → final summary with feedback buttons (👍/👎)

### Buttons & Callbacks

Every result includes inline buttons for feedback and navigation:

```python
# Example: Ask result with feedback buttons
buttons = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="👍", callback_data=f"feedback:accept:{ref}"),
        InlineKeyboardButton(text="👎", callback_data=f"feedback:reject:{ref}"),
    ],
    [
        InlineKeyboardButton(text="📊 View Sources", callback_data=f"sources:{job_id}"),
        InlineKeyboardButton(text="🧠 Brainstorm", callback_data="open_miniapp:brainstorm"),
    ]
])

await message.answer(answer_text, reply_markup=buttons, parse_mode="HTML")

@dp.callback_query(F.data.startswith("feedback:"))
async def on_feedback(query: CallbackQuery):
    _, verdict, ref = query.data.split(":")
    await engine.submit(Feedback(user=str(query.from_user.id), ref=ref, verdict=verdict))
    await query.answer("✅ Feedback recorded")
```

### Opening the Mini App from Bot

Use inline keyboards to launch the Mini App webview:

```python
# Open Mini App for brainstorming or settings
launch_button = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(
        text="💬 Open Brainstorm",
        web_app=WebAppInfo(url=f"{MINIAPP_URL}/brainstorm")
    )]
])

await message.answer("Start a brainstorm conversation…", reply_markup=launch_button)
```

---

## 3. Mini App Webview Surface (Rich UI)

The Mini App is a web application hosted on HTTPS, embedded in Telegram's webview. It is the **full-featured interface** for all complex interactions.

### Mini App Features

1. **Chat/Ask Tab** — streaming chat interface
   - Input field + send button
   - Message stream (user queries + assistant responses with citations)
   - Source sidebar or expandable cite blocks
   - Feedback buttons (👍/👎) on responses

2. **Brainstorm Tab** — multi-turn conversation (stateful by session_id)
   - Thread-like view (inquiry turns + ideation proposals)
   - Each turn streams live
   - "Save idea" button submits `Opportunities(action="save", ref=…)`
   - Research-in-progress interstitials if the Brainstorming Agent triggers Research Agent

3. **Research Graph Tab** — interactive visualization
   - Citation/knowledge graph rendered via Cytoscape.js or vis-network
   - Zoom + pan + search
   - Node details on hover (title, abstract, authors, link)
   - Interest-linked nodes highlighted
   - Edge types (cites, refines, supports, etc.)

4. **Interests Tab** — interest model display
   - Timeline slider (last 7 days / 30 days / all time)
   - Cards ranked by strength
   - Quick-add / remove buttons
   - Manual research trigger

5. **Settings Tab** — preferences & management
   - Toggle connectors (GitHub, browser, Slack)
   - Manage tracked topics
   - Manage sources (research depth defaults, etc.)
   - Log out / account info

### Mini App Authentication

Telegram provides **`initData`** — an HMAC-signed payload containing user info and timestamp. Validate it server-side to authenticate:

```python
# src/adapters/telegram/auth.py
import hmac
import hashlib
from urllib.parse import parse_qs

def validate_init_data(init_data: str, bot_token: str) -> dict | None:
    """Validate Telegram Mini App initData signature."""
    try:
        data = parse_qs(init_data)
        signature = data.get("hash", [None])[0]
        
        # Build the data_check_string (sorted pairs minus hash)
        pairs = sorted([f"{k}={v[0]}" for k, v in data.items() if k != "hash"])
        data_check_string = "\n".join(pairs)
        
        # Compute HMAC-SHA256
        secret_key = hashlib.sha256(bot_token.encode()).digest()
        computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        if computed_hash != signature:
            return None
        
        # Extract user ID from user_id field (JSON-encoded)
        import json
        user_data = json.loads(data.get("user", [None])[0] or "{}")
        return {"user_id": user_data.get("id"), "timestamp": int(data.get("auth_date", [0])[0])}
    except Exception:
        return None
```

**WebSocket auth:** Pass `initData` as a query parameter; validate on connect.

---

## 4. Backend API Design

### Framework Choice: FastAPI + aiohttp WebSocket

**Recommendation: FastAPI** for REST + WebSocket streaming.

**Why:**
- Native async/await
- Built-in OpenAPI docs
- Seamless integration with `PersonalAssistantEngine` (already async)
- WebSocket support out-of-the-box
- Easy middleware for auth validation

### REST Endpoints

All endpoints map 1:1 to Command types. Response format is uniform:

```json
{
  "ok": true,
  "job_id": "uuid-here",
  "status": "submitted"
}
```

#### Submit Command Endpoints

```
POST /api/v1/ask
  Body: { "query": "...", "session_id": "optional" }
  Returns: { "ok": true, "job_id": "..." }

POST /api/v1/brainstorm
  Body: { "text": "...", "session_id": "uuid" }
  Returns: { "ok": true, "job_id": "..." }

POST /api/v1/research
  Body: { "topic": "...", "depth": "normal|deep|shallow" }
  Returns: { "ok": true, "job_id": "..." }

POST /api/v1/feedback
  Body: { "ref": "...", "verdict": "accept|reject", "note": "optional" }
  Returns: { "ok": true }

POST /api/v1/opportunities
  Body: { "action": "list|save|dismiss", "ref": "optional" }
  Returns: { "ok": true, "payload": { ... } }

POST /api/v1/interests/add
  Body: { "topic": "...", "strength": 0.5 }
  Returns: { "ok": true }

POST /api/v1/graph
  Body: { "kind": "knowledge|citation", "topic": "optional", "depth": 2 }
  Returns: { "ok": true, "graph": { "nodes": [...], "edges": [...] } }
```

#### Query/Read Endpoints

```
GET /api/v1/interests
  Query: ?filter=active&timeline=30d
  Returns: { "ok": true, "interests": [...] }

GET /api/v1/digest
  Query: ?date=YYYY-MM-DD
  Returns: { "ok": true, "digest": { ... } }

GET /api/v1/job/{job_id}/status
  Returns: { "ok": true, "status": "running|done", "progress": { ... } }

GET /api/v1/graph/{id}
  Returns: { "ok": true, "graph": { "nodes": [...], "edges": [...] } }

GET /api/v1/session/{session_id}/history
  Returns: { "ok": true, "turns": [...] }
```

### WebSocket Streaming Endpoint

```
WS /api/v1/stream/{job_id}
  Query: ?init_data=...&user_id=...
  
  On connect:
    1. Validate initData
    2. Subscribe to engine.events(job_id)
    3. Stream each event as JSON
  
  On disconnect:
    - Unsubscribe
```

**Event format (JSON):**

```json
{
  "type": "started",
  "job_id": "uuid",
  "kind": "ask"
}

{
  "type": "progress",
  "job_id": "uuid",
  "phase": "searching",
  "message": "Querying knowledge base…",
  "progress_percent": 45
}

{
  "type": "message",
  "job_id": "uuid",
  "role": "assistant",
  "text": "Here's what I found…",
  "citations": [
    {"title": "Paper Title", "url": "...", "source": "Scholar"}
  ]
}

{
  "type": "result",
  "job_id": "uuid",
  "ok": true,
  "payload": {
    "summary": "...",
    "opportunities": [...]
  }
}
```

### Event → UI Rendering Map

| Event | Mini App Rendering |
|-------|-------------------|
| `Started` | Show "Loading…" spinner; enable Cancel button |
| `Progress` | Update progress bar; show phase message |
| `Message(role=assistant)` | Append assistant turn; render citations as inline links/expandable |
| `Message(role=user)` | Echo user input at top (for brainstorm) |
| `Result(ok=True)` | Show summary section; render payload (e.g., opportunities list with Save/Dismiss) |
| `Result(ok=False)` | Show error message; offer "View details" → logs |

---

## 5. Research-Paper Graph Interface

### Graph Data Model

The **UnifiedKnowledgeStore** (SQLite) already tracks:
- Papers (title, authors, abstract, year, url)
- Concepts (name, definition, related papers)
- Edges (cites, refines, supports, criticizes, etc.)
- Interest links (which concepts/papers the user is interested in)

### Graph Fetch Endpoint

```python
# GET /api/v1/graph/{kind}/{topic}
# kind = "knowledge" | "citation"
# Returns: nodes + edges ready for visualization

async def fetch_graph(kind: str, topic: str | None, depth: int = 2):
    """Fetch graph subgraph for visualization."""
    if kind == "citation":
        # Start from a paper matching 'topic'
        papers = await store.search_papers(topic, limit=1)
        if not papers:
            return {"nodes": [], "edges": []}
        root_paper_id = papers[0]["id"]
        
        # Get citing + cited papers (2 hops)
        subgraph = await store.get_citation_subgraph(root_paper_id, depth=depth)
    else:  # knowledge
        # Start from a concept matching 'topic'
        concepts = await store.search_concepts(topic, limit=1)
        if not concepts:
            return {"nodes": [], "edges": []}
        root_concept_id = concepts[0]["id"]
        
        # Get related concepts (2 hops)
        subgraph = await store.get_concept_subgraph(root_concept_id, depth=depth)
    
    # Build visualization format
    nodes = [
        {
            "id": node["id"],
            "label": node["title"] or node["name"],
            "type": "paper" if kind == "citation" else "concept",
            "metadata": {
                "abstract": node.get("abstract", ""),
                "url": node.get("url", ""),
                "authors": node.get("authors", []),
                "year": node.get("year")
            },
            "highlighted": node.get("is_interest", False)
        }
        for node in subgraph["nodes"]
    ]
    
    edges = [
        {
            "from": edge["source_id"],
            "to": edge["target_id"],
            "label": edge["relation_type"],
            "weight": edge.get("strength", 1.0)
        }
        for edge in subgraph["edges"]
    ]
    
    return {"nodes": nodes, "edges": edges, "root_id": papers[0]["id"] if kind == "citation" else concepts[0]["id"]}
```

### Graph Visualization Library

**Recommendation: Cytoscape.js**

**Why:**
- Excellent force-directed + hierarchical layouts
- Fast pan/zoom on large graphs (100+ nodes)
- Built-in search, click handlers, styling
- Active community; works well with vanilla TS/React
- License: MIT

**Alternative: vis-network** — simpler API, less powerful, but good for <100 nodes.

**Integration:**

```typescript
// src/miniapp/components/ResearchGraph.tsx
import CytoscapeComponent from "react-cytoscapejs";
import Cytoscape from "cytoscape";
import fcose from "cytoscape-fcose";

Cytoscape.use(fcose);

export function ResearchGraph({ graphData }) {
  const elements = [
    ...graphData.nodes.map(n => ({ data: n })),
    ...graphData.edges.map(e => ({ data: e })),
  ];

  const layout = {
    name: "fcose",
    directed: true,
    animate: true,
  };

  const style = [
    {
      selector: "node",
      style: {
        "background-color": node =>
          node.data("highlighted") ? "#FF6B6B" : "#4A90E2",
        label: "data(label)",
        "text-valign": "center",
      },
    },
    {
      selector: "edge",
      style: {
        "target-arrow-shape": "triangle",
        "line-color": "#ccc",
        label: "data(label)",
      },
    },
  ];

  return <CytoscapeComponent elements={elements} style={{ height: "600px" }} layout={layout} stylesheet={style} />;
}
```

---

## 6. Mini App Frontend Stack

### Recommendation: **React 18 + Vite + TypeScript + Telegram WebApp SDK**

**Stack rationale:**
- **React**: Component reuse; ecosystem (routing, state); matches brainstorming-agent pattern (LangGraph UI is often React)
- **Vite**: Fast HMR; minimal config; produces tiny bundles (critical for mobile)
- **TypeScript**: Type safety; command/event contracts mirrored from backend
- **Telegram WebApp SDK**: Official bridge to Telegram client (haptic feedback, back button, window height, dark mode)

**UI library options:**
- **TailwindCSS** (recommended): Utility-first; responsive; no component library overhead
- **Shadcn/ui**: Pre-built components on Tailwind; good for quick iteration
- **Material-UI**: Heavier; overkill for a Mini App

### Directory Structure

```
miniapp/
├── public/
│   ├── index.html           # Single entry point
│   └── manifest.json        # PWA manifest (for offline, if needed)
├── src/
│   ├── main.tsx             # Entry; initialize Telegram SDK
│   ├── app.tsx              # Main app layout
│   ├── types.ts             # Command/Event types (mirror backend)
│   ├── api/
│   │   ├── client.ts        # HTTP + WebSocket client (fetch + ws libs)
│   │   └── auth.ts          # Extract & validate initData
│   ├── hooks/
│   │   ├── useJob.ts        # Subscribe to job events via WebSocket
│   │   ├── useInterests.ts  # Fetch interests
│   │   └── useBrainstorm.ts # Multi-turn session state
│   ├── components/
│   │   ├── Chat/
│   │   │   ├── ChatView.tsx       # Message list + input
│   │   │   ├── Message.tsx        # Single message with cites
│   │   │   └── Citations.tsx      # Cite block
│   │   ├── Brainstorm/
│   │   │   ├── BrainstormView.tsx # Multi-turn thread view
│   │   │   └── Turn.tsx           # Single turn + proposals
│   │   ├── Graph/
│   │   │   ├── ResearchGraph.tsx  # Cytoscape wrapper
│   │   │   └── GraphControls.tsx  # Search, zoom, filters
│   │   ├── Interests/
│   │   │   └── InterestCard.tsx   # Single interest + actions
│   │   ├── Settings/
│   │   │   ├── SettingsView.tsx   # All settings tabs
│   │   │   └── ConnectorToggle.tsx
│   │   └── Layout/
│   │       ├── Header.tsx         # Top bar + title
│   │       └── TabBar.tsx         # Bottom tab nav
│   ├── pages/
│   │   ├── Ask.tsx          # Tab: /ask
│   │   ├── Brainstorm.tsx   # Tab: /brainstorm
│   │   ├── Graph.tsx        # Tab: /graph
│   │   ├── Interests.tsx    # Tab: /interests
│   │   └── Settings.tsx     # Tab: /settings
│   ├── stores/              # Zustand (for session state)
│   │   ├── brainstormStore.ts
│   │   └── settingsStore.ts
│   └── styles/
│       ├── tailwind.css     # Tailwind imports
│       └── globals.css      # App-wide overrides
├── vite.config.ts
├── tsconfig.json
├── tailwind.config.js
└── package.json
```

---

## 7. Telegram-Specific Mechanics

### Bot Library Choice: **aiogram**

**Recommendation: aiogram v3** (async-first, modern Python, well-maintained).

**Why over python-telegram-bot:**
- Async by default (PersonalAssistantEngine is already async)
- Filters + handlers are composable and ergonomic
- FSM (Finite State Machine) support for multi-step commands
- Active maintenance and community

### HTTPS Hosting Requirement

Telegram Mini Apps **must be served over HTTPS** (even in development).

**Option A: Local development with ngrok/Cloudflare Tunnel (recommended for dev)**
```bash
# Terminal 1: Backend service
poetry run python -m src.adapters.telegram.app

# Terminal 2: Expose to HTTPS
ngrok http 8000  # exposes http://localhost:8000 as https://...ngrok.io

# Update .env: MINIAPP_URL=https://...ngrok.io
```

**Pros:** Fast iteration; real Telegram bot testing; no deployment friction
**Cons:** Tunnel URL changes; not prod-ready

**Option B: Self-hosted HTTPS (production)**
- Use a reverse proxy (nginx/Caddy) with Let's Encrypt
- Domain + SSL cert required
- More stable; production-grade

**Option C: Deployment platform (Fly.io / Railway / Render)**
- Automatic HTTPS
- Simpler ops
- Cost: $5–$25/month

**Recommendation for now:** Start with **Option A (ngrok)** for rapid development; move to **Option C (Fly.io)** for production after Mini App is stable.

### Mini App URL Registration

In Telegram Bot settings (via `@BotFather`):
```
/setmenu
<select your bot>
web_app https://your-mini-app-url.com
```

The bot can then launch the Mini App with:
```python
InlineKeyboardButton(
    text="Open Mini App",
    web_app=WebAppInfo(url="https://your-mini-app-url.com/brainstorm")
)
```

### Long-Polling vs Webhook

**Recommendation: Long-polling for now** (simpler setup; no inbound firewall requirement).

**Webhook mode** is available but requires public HTTP endpoint + SSL cert validation. Long-polling has lower throughput but is sufficient for a single user.

```python
# src/adapters/telegram/app.py
async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    
    # ... register handlers ...
    
    # Long-poll
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
```

---

## 8. Command/Feature Parity Matrix

| Command | Bot Chat | Mini App Tab | Notes |
|---------|----------|--------------|-------|
| `/ask <query>` | ✅ Inline | ✅ Ask Tab | Streams response + cites |
| `/brainstorm [topic]` | ✅ Button → launch | ✅ Brainstorm Tab | Multi-turn, stateful session |
| `/interests` | ✅ Inline list | ✅ Interests Tab | Timeline filter |
| `/research <topic>` | ✅ Inline progress | ✅ Ask/Brainstorm (auto-trigger) | Manual + auto |
| `/graph` | ✅ Button → launch | ✅ Graph Tab | Citation or concept graph |
| `/digest [date]` | ✅ Inline | ✅ (read-only in Ask/home) | Proactive digest also posts to bot |
| `/opps` | ✅ Button list | ✅ (Brainstorm proposals) | Save/dismiss proposals |
| `/ingest [connector]` | ✅ Inline | — | Daemon trigger; bot-only |
| `/prefs` / Settings | ✅ Button → launch | ✅ Settings Tab | Connectors, topics, sources |
| Feedback buttons | ✅ Inline (👍/👎) | ✅ (inline in messages) | Same contract |
| Status/logs | — | ✅ Job status in Ask | View logs via `/status <job>` in bot |

**Parity rule:** Every command accessible via bot chat is also accessible (when appropriate) via Mini App. No feature locked to one interface.

---

## 9. Phased Implementation Roadmap

### Phase 1: Backend API + Auth (Weeks 1–2)
**Deliverable:** REST API + WebSocket infrastructure, Telegram auth validation.

**Modules:**
- `src/adapters/telegram/api.py` — FastAPI app + endpoints
- `src/adapters/telegram/auth.py` — initData validation
- `src/adapters/telegram/models.py` — Pydantic request/response models
- `tests/test_telegram_api.py` — API tests (parity with commands)

**Acceptance:**
- [ ] All REST endpoints functional
- [ ] WebSocket streaming works
- [ ] Auth validation passes security review
- [ ] API docs auto-generated (FastAPI/OpenAPI)

### Phase 2: Bot Handler + Basic Chat (Weeks 2–3)
**Deliverable:** Telegram bot in long-poll mode; `/ask`, `/interests`, feedback buttons working.

**Modules:**
- `src/adapters/telegram/bot_handler.py` — aiogram handlers
- `src/adapters/telegram/renderers.py` — Event → Telegram message formatting
- `src/adapters/telegram/app.py` — Main app (bot + API unified)
- `tests/test_telegram_bot.py` — Handler + render tests

**Acceptance:**
- [ ] `/ask` returns streamed responses
- [ ] Feedback buttons work end-to-end
- [ ] /interests card list renders
- [ ] Bot responds within 3 seconds

### Phase 3: Mini App Chat + Brainstorm Streaming (Weeks 3–5)
**Deliverable:** Mini App MVP; Ask + Brainstorm tabs with live streaming.

**Modules:**
- `miniapp/src/api/client.ts` — HTTP + WebSocket client
- `miniapp/src/components/Chat/ChatView.tsx` — Chat interface
- `miniapp/src/components/Brainstorm/BrainstormView.tsx` — Multi-turn view
- `miniapp/src/hooks/useJob.ts` — Event subscription logic
- `tests/miniapp.test.ts` — Component tests

**Acceptance:**
- [ ] Chat streams responses in real-time
- [ ] Brainstorm multi-turn works; session persists
- [ ] Citations render with links
- [ ] WebSocket reconnection handles drops

### Phase 4: Research-Paper Graph UI (Weeks 5–7)
**Deliverable:** Interactive citation/knowledge graph visualization.

**Modules:**
- `src/adapters/telegram/graph.py` — Graph fetch endpoint
- `miniapp/src/components/Graph/ResearchGraph.tsx` — Cytoscape wrapper
- `miniapp/src/pages/Graph.tsx` — Graph tab
- `tests/test_graph_fetch.py` — Graph query tests

**Acceptance:**
- [ ] Graph renders with 50+ nodes smoothly
- [ ] Zoom, pan, search work
- [ ] Interest nodes highlighted
- [ ] Click → show paper details

### Phase 5: Interests + Digest + Notifications (Weeks 7–8)
**Deliverable:** Full Interests tab; proactive digest delivery to bot.

**Modules:**
- `miniapp/src/pages/Interests.tsx` — Interest model view + timeline
- `miniapp/src/pages/Settings.tsx` — All settings tabs
- `src/adapters/telegram/digest.py` — Digest formatter + posting
- `src/adapters/telegram/notifications.py` — Event-triggered alerts

**Acceptance:**
- [ ] Interests tab shows strength timeline
- [ ] Add/remove topics from Mini App
- [ ] Digest posts to bot chat on schedule
- [ ] Settings persist across sessions

### Phase 6: Polish & Deployment (Week 8+)
**Deliverable:** Production-ready; docs, security audit, load testing.

- [ ] Code review & security audit
- [ ] E2E tests (user flows: ask → graph → brainstorm)
- [ ] Deployment to Fly.io / production host
- [ ] Migrate Slack docs to backlog; link to this RFC in CLAUDE.md

---

## 10. Open Questions & Decision Points

1. **Hosting & DevOps**
   - **Decision needed:** Self-hosted (nginx + Let's Encrypt) vs managed platform (Fly.io / Railway)?
   - **Impact:** Dev iteration speed, ops burden, cost, HTTPS setup
   - **Recommendation:** Start with Fly.io; simpler ops; automatic HTTPS

2. **Frontend Framework**
   - **Decision needed:** React + Vite vs Vue + Vite vs vanilla TypeScript?
   - **Impact:** Bundle size, learning curve for team, component ecosystem
   - **Recommendation:** React; ecosystem + pattern alignment with brainstorming-agent

3. **Graph Visualization Library**
   - **Decision needed:** Cytoscape.js vs vis-network vs d3-force?
   - **Impact:** Performance (large graphs), customization, learning curve
   - **Recommendation:** Cytoscape.js for production (better perf); vis-network if MVP is acceptable

4. **Session Persistence**
   - **Decision needed:** Store brainstorm sessions in SQLite (permanent) or in-memory with client-side replay?
   - **Impact:** Recovery from crashes, storage overhead, privacy
   - **Recommendation:** SQLite; align with research-agent KB design; enables "resume brainstorm" feature

5. **Mini App Auth Scope**
   - **Decision needed:** Validate initData once per session (on WebSocket connect) or on every request?
   - **Impact:** Security (replay attack risk), API latency
   - **Recommendation:** Per-request validation; include timestamp check (must be < 5 min old)

6. **Telegram Bot Features to Defer**
   - **Decision needed:** Which advanced features to backlog (inline queries, group chat support, reactions)?
   - **Impact:** Initial scope creep
   - **Recommendation:** Start with single-user DMs; group chat in future phase

7. **Backward Compat with Slack**
   - **Decision needed:** Keep Slack gateway code in tree but disabled, or delete entirely?
   - **Impact:** Maintenance burden, ability to re-enable Slack later
   - **Recommendation:** Keep code; disable in config; move docs to backlog with links

---

## 11. Backlog Note: Slack Gateway

**Status:** Moved to backlog; Telegram Mini App is the primary gateway as of now.

**Reference:** [02-slack-gateway.md](docs/impl/02-slack-gateway.md) contains the complete Slack adapter design. If Slack is re-prioritized, use that doc as the starting point. The command semantics and event-rendering patterns are transferable to any new adapter.

---

## Related Documents

- [01-cli-and-core-engine.md](docs/impl/01-cli-and-core-engine.md) — Command/Event contracts
- [02-slack-gateway.md](docs/impl/02-slack-gateway.md) — Slack adapter (now backlog; reference design)
- [06-research-agent.md](docs/plans/research-agent.plan.md) — Research Agent (feeds graph data)
- [Brainstorming Agent Plan](docs/brainstorming-agent.plan.md) — Multi-turn conversation agent
- [Telegram Bot API](https://core.telegram.org/bots/api) — Official reference
- [Telegram Mini Apps](https://core.telegram.org/bots/webapps) — Official spec

---

## Glossary

- **Mini App** — A web application embedded in Telegram's webview; runs in the user's Telegram client
- **initData** — HMAC-signed authentication payload provided by Telegram to the Mini App
- **Bot Chat** — The main Telegram chat interface; supports commands and buttons
- **Session ID** — Unique identifier for a brainstorm conversation; Telegram message thread_ts equivalent
- **Job ID** — UUID assigned by the engine when a command is submitted; used to stream events
- **EventBus** — The pub-sub system that streams `Event` objects to the interface layer
