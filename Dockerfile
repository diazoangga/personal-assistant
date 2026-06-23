# Multi-stage build: React frontend + Python backend

# Stage 1: Build React frontend
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

# Copy frontend code
COPY frontend/package.json frontend/package-lock.json* frontend/yarn.lock* ./

# Install dependencies
RUN npm ci || yarn install --frozen-lockfile || npm install

# Copy source
COPY frontend/ .

# Build
RUN npm run build

# Stage 2: Python backend with static frontend
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

# Copy built frontend static files
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Create .env placeholder
RUN touch .env

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/api/health')" || exit 1

# Run the unified service
CMD ["poetry", "run", "python", "-m", "src.adapters.telegram.app"]
