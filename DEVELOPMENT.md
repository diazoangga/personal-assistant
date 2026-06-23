# Telegram Mini App - Development Guide

This guide explains how to set up and run the Personal Assistant Telegram Mini App locally.

## Quick Start (30 minutes)

### Prerequisites
- Python 3.10+
- Node.js 18+
- Docker & Docker Compose (for Qdrant and containerized deployment)
- Telegram Bot Token (create via @BotFather)

### 1. Clone & Configure

```bash
git clone <repo>
cd personal-assistant

# Create .env from template
cp .env.example .env

# Edit .env with your tokens
# - TELEGRAM_BOT_TOKEN: Get from @BotFather on Telegram
# - OPENROUTER_API_KEY: Get from https://openrouter.ai
# - GITHUB_TOKEN: Get from GitHub settings
```

### 2. Set Up Backend

```bash
cd backend  # (if in a separate directory; otherwise: cd . for root)

# Install Python dependencies
poetry install

# Activate virtual environment
poetry shell
# OR prefix commands with `poetry run`
```

### 3. Set Up Frontend

```bash
cd frontend

# Install Node dependencies
npm install
# OR
yarn install
```

### 4. Start Services

**Terminal 1 - Backend (daemon + API + bot):**
```bash
cd backend
poetry run python -m src.adapters.telegram.app
```

You should see:
```
======================================================================
Starting Unified Telegram Mini App Backend
======================================================================
[1/4] Initializing PersonalAssistantEngine...
      ✓ Engine initialized
[2/4] Setting up API authentication...
      ✓ API dependencies ready
[3/4] Starting daemon service...
      ✓ Daemon started
[4/4] Starting Telegram bot...
      ✓ Bot started (long-polling)
======================================================================
Backend running at http://0.0.0.0:8000
Mini App URL: http://localhost:5173
======================================================================
```

**Terminal 2 - Frontend Dev Server:**
```bash
cd frontend
npm run dev
```

Frontend will be available at: http://localhost:5173

**Terminal 3 (Optional) - ngrok Tunnel for HTTPS:**
```bash
ngrok http 8000
```

Telegram requires HTTPS. Copy the ngrok URL (e.g., `https://abc123.ngrok.io`) and:
1. Update in `.env`: `MINI_APP_URL=https://abc123.ngrok.io`
2. Update your Telegram bot's App Menu settings

### 5. Test the Bot

1. Open Telegram
2. Message your bot (the one you created with @BotFather)
3. Type `/start` to see the main menu
4. Click "Open Mini App" button to launch the React web view
5. Try asking a question or starting a brainstorm session

## Architecture Overview

The system runs three concurrent async services in the same container:

```
┌─────────────────────────────────────┐
│  Python Backend (asyncio)           │
├─────────────────────────────────────┤
│                                     │
│  1. Daemon Loop (every 15 min)      │
│     → GitHub → Interest Agent       │
│                                     │
│  2. FastAPI Server (:8000)          │
│     → REST API                      │
│     → WebSocket (live events)       │
│                                     │
│  3. Telegram Bot Handler            │
│     → aiogram long-polling          │
│                                     │
│  Shared State:                      │
│     → PersonalAssistantEngine       │
│     → knowledge.db (SQLite)         │
│                                     │
└─────────────────────────────────────┘
       ↑                        ↑
    Telegram            Mini App (React)
    Bot API             Browser/Webview
```

## Local Development Workflow

### API Development

Add new REST endpoints in `src/adapters/telegram/handlers.py`:

```python
@router.post("/my-endpoint")
async def my_endpoint(
    request: MyRequest,
    user: TelegramUser = Depends(get_user),
    deps: TelegramDependencies = Depends(get_deps),
) -> dict[str, str]:
    """Description of my endpoint."""
    cmd = MyCommand(user=user.to_command_user_field(), **request.dict())
    job_id = await deps.engine.submit(cmd)
    return {"job_id": job_id, "kind": "my_command"}
```

The API will automatically:
- Validate the `initData` from Telegram
- Stream events via WebSocket or SSE
- Map to engine commands

### Frontend Development

Add new pages in `frontend/src/pages/`:

```typescript
export const MyPage: React.FC = () => {
  const [state, setState] = useState('');

  const handleSubmit = async () => {
    const result = await api.myEndpoint(state);
    for await (const event of api.streamEventsWebSocket(result.job_id)) {
      // Handle events
    }
  };

  return <div>{/* UI */}</div>;
};
```

Then add the page to the navigation tabs in `App.tsx`.

### Bot Development

Add new commands in `src/adapters/telegram/bot.py`:

```python
@self.router.message(Command("mycommand"))
async def cmd_mycommand(message: Message) -> None:
    """Handle /mycommand."""
    # Use self.engine to submit commands
    # Use self.bot.send_message() to respond
```

### Testing Locally

```bash
# Run tests
poetry run pytest tests/ -v

# Type checking
poetry run mypy src/

# Format code
poetry run black src/ frontend/src/

# Lint
poetry run ruff check src/
```

## Using Docker Compose (Alternative)

For a complete containerized setup including Qdrant:

```bash
# Build and start all services
docker-compose up --build

# Backend: http://localhost:8000
# Qdrant: http://localhost:6333
# Frontend: http://localhost:5173 (if using separate frontend service)
```

## Debugging

### Backend Logs

The daemon and API both log to the console and `./data/daemon.log`:

```bash
# Watch daemon logs
tail -f ./data/daemon.log

# Search for specific events
grep "Research trigger" ./data/daemon.log
```

### API Debugging

Check FastAPI automatic docs:
```
http://localhost:8000/docs
```

### Frontend Debugging

Use browser DevTools:
1. Right-click → Inspect
2. Check Console tab for JS errors
3. Use Network tab to inspect API calls

### Telegram Bot Debugging

The bot logs to console. Set `log_level = DEBUG` in daemon config to see more details.

## Troubleshooting

### "TELEGRAM_BOT_TOKEN not found"
- Copy `.env.example` to `.env`
- Add your bot token from @BotFather

### "Connection refused" to localhost:8000
- Ensure backend is running: `poetry run python -m src.adapters.telegram.app`
- Check port 8000 is not in use: `lsof -i :8000`

### "Failed to authenticate with backend"
- Ensure `initData` is being sent correctly
- Check `.env` has same `TELEGRAM_BOT_TOKEN` as bot
- Verify HMAC validation in `src/adapters/telegram/auth.py`

### Frontend can't reach backend
- Check CORS is enabled in `src/adapters/telegram/app.py`
- Verify `VITE_API_URL` matches backend host
- If using ngrok, update `MINI_APP_URL` in `.env`

### Qdrant connection errors
- Ensure Qdrant is running: `docker ps | grep qdrant`
- Check firewall allows 6333
- Verify `QDRANT_HOST` and `QDRANT_PORT` in `.env`

## Next Steps

1. **Implement graph visualization** - Use Cytoscape.js in `ResearchPage.tsx`
2. **Add more bot commands** - `/research`, `/graph`, etc. in `bot.py`
3. **Implement interests loading** - Complete the `InterestsPage.tsx`
4. **Add unit tests** - Create test files in `tests/`
5. **Deploy to production** - Use Fly.io or self-hosted with Docker

## Resources

- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [aiogram Docs](https://aiogram.dev/)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [Telegram Mini App Docs](https://core.telegram.org/bots/webapps)
- [React Docs](https://react.dev/)
- [Vite Docs](https://vitejs.dev/)
