.PHONY: dev test lint format docker-up docker-down clean help

PYTHON = .venv/bin/python
PIP = .venv/bin/pip
pytest = .venv/bin/pytest
ruff = .venv/bin/ruff

help:
	@echo "Available commands:"
	@echo "  make dev         - Start FastAPI dev server"
	@echo "  make test        - Run all tests using pytest"
	@echo "  make lint        - Lint code using Ruff"
	@echo "  make format      - Format code using Ruff"
	@echo "  make docker-up   - Build and start application via docker-compose"
	@echo "  make docker-down - Stop and clean up containers"
	@echo "  make clean       - Remove cache and temporary files"

dev:
	$(PYTHON) -m uvicorn src.api.app:app --reload --host 127.0.0.1 --port 8000

test:
	$(pytest) tests/ -v

lint:
	$(ruff) check src/ tests/

format:
	$(ruff) format src/ tests/

docker-up:
	docker-compose up -d --build

docker-down:
	docker-compose down

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
