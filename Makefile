# Personal Assistant Makefile

.PHONY: help deps dev api-dev test test-cov lint typecheck format clean migration docker-up docker-down docs

# Default target
help:
	@echo "Personal Assistant - Development Commands"
	@echo ""
	@echo "Setup:"
	@echo "  deps          Install dependencies using Poetry"
	@echo "  dev           Install dev dependencies and setup pre-commit hooks"
	@echo "  clean         Remove build artifacts and cache"
	@echo ""
	@echo "Development:"
	@echo "  dev           Run the CLI in development mode"
	@echo "  api-dev       Run API server for development (if applicable)"
	@echo "  lint          Run linter (ruff)"
	@echo "  format        Format code with black"
	@echo "  typecheck     Run type checker (mypy)"
	@echo ""
	@echo "Testing:"
	@echo "  test          Run tests"
	@echo "  test-cov      Run tests with coverage report"
	@echo "  test-watch    Run tests in watch mode"
	@echo ""
	@echo "Database:"
	@echo "  migration     Run database migrations"
	@echo "  docker-up     Start Qdrant database"
	@echo "  docker-down   Stop Qdrant database"
	@echo ""
	@echo "Documentation:"
	@echo "  docs          Generate documentation"
	@echo ""

# Setup
deps:
	@echo "Installing dependencies with Poetry..."
	poetry install --no-root
	@echo "Dependencies installed successfully!"

dev-setup: deps
	@echo "Setting up development environment..."
	poetry install --with dev
	@echo "Development environment ready!"

# Development
dev:
	@echo "Starting Personal Assistant CLI..."
	poetry run pa repl

api-dev:
	@echo "Starting API server (placeholder)..."
	@echo "Note: API server not yet implemented"
	@echo "Use 'poetry run pa repl' for interactive CLI"

# Testing
test:
	@echo "Running tests..."
	poetry run pytest

test-cov:
	@echo "Running tests with coverage..."
	poetry run pytest --cov=src --cov-report=term-missing --cov-report=html
	@echo "Coverage report generated in htmlcov/index.html"

test-watch:
	@echo "Running tests in watch mode..."
	poetry run pytest -w

test-single:
	@echo "Running single test file: $(file)"
	poetry run pytest $(file) -v

# Code Quality
lint:
	@echo "Running linter..."
	poetry run ruff check src/ tests/

lint-fix:
	@echo "Fixing lint errors..."
	poetry run ruff check src/ tests/ --fix

format:
	@echo "Formatting code..."
	poetry run black src/ tests/

format-check:
	@echo "Checking code formatting..."
	poetry run black src/ tests/ --check

typecheck:
	@echo "Running type checker..."
	poetry run mypy src/

check-all: lint format-check typecheck test
	@echo "All checks passed!"

# Database
migration:
	@echo "Running database migrations..."
	@echo "Note: Migrations handled automatically by storage layer initialization"
	@echo "To reset databases, delete files in ./data/ directory"

migrate-reset:
	@echo "Resetting databases..."
	rm -rf ./data/*.db
	@echo "Databases reset. They will be recreated on next run."

# Docker
docker-up:
	@echo "Starting Qdrant database..."
	docker compose up -d
	@echo "Qdrant started on http://localhost:6333"

docker-down:
	@echo "Stopping Qdrant database..."
	docker compose down

docker-logs:
	@echo "Showing Qdrant logs..."
	docker compose logs -f

docker-clean:
	@echo "Cleaning Docker resources..."
	docker compose down -v
	docker system prune -f

# Documentation
docs:
	@echo "Generating documentation..."
	@echo "Note: Documentation generation not yet configured"
	@echo "See IMPLEMENTATION_STATUS.md for current status"

# Utilities
clean:
	@echo "Cleaning build artifacts..."
	rm -rf dist/ build/ *.egg-info .pytest_cache/ .mypy_cache/ htmlcov/
	rm -rf .coverage coverage.xml __pycache__/ src/__pycache__/
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	@echo "Clean complete!"

env-check:
	@echo "Checking environment..."
	@echo "Python version: $$(python --version)"
	@echo "Poetry version: $$(poetry --version)"
	@if [ -f ".env" ]; then \
		echo "✓ .env file exists"; \
	else \
		echo "✗ .env file missing. Copy .env.example to .env"; \
	fi

install-hooks:
	@echo "Installing pre-commit hooks..."
	@echo "# Pre-commit hooks placeholder" > .git/hooks/pre-commit
	@echo "poetry run ruff check src/ tests/" >> .git/hooks/pre-commit
	@echo "poetry run black src/ tests/ --check" >> .git/hooks/pre-commit
	chmod +x .git/hooks/pre-commit
	@echo "Pre-commit hooks installed!"

# Quick start for new developers
bootstrap: clean deps docker-up
	@echo "Bootstrap complete! Next steps:"
	@echo "1. Copy .env.example to .env and fill in API keys"
	@echo "2. Run 'make dev' to start the CLI"
	@echo "3. Run 'make test' to verify everything works"
