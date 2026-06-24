# Backend-only image: engine + daemon + local web API.
# The frontend is now a separate Tauri desktop app (personal-assistant-desktop
# repo) and is NOT built or served here.

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy pyproject.toml and poetry.lock
COPY pyproject.toml poetry.lock* ./

# Install Poetry
RUN pip install poetry && poetry config virtualenvs.in-project true

# Install Python dependencies
RUN poetry install --no-dev --no-interaction --no-ansi

# Copy backend code
COPY src/ ./src/
COPY config/ ./config/

# Create .env placeholder
RUN touch .env

# Local web API port (see docs/WEB_API.md)
EXPOSE 8787

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8787/api/health')" || exit 1

# Run the local web API (engine + daemon + REST/SSE/WS).
# Implements the contract in docs/WEB_API.md (src/adapters/api).
CMD ["poetry", "run", "python", "-m", "src.adapters.api"]
