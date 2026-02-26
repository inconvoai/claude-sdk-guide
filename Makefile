SHELL := /bin/bash
.DEFAULT_GOAL := help

ROOT_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
BACKEND_DIR := $(ROOT_DIR)/backend
FRONTEND_DIR := $(ROOT_DIR)/frontend
BACKEND_ENV := $(BACKEND_DIR)/.env
FRONTEND_ENV := $(FRONTEND_DIR)/.env.local
BACKEND_ENV_EXAMPLE := $(BACKEND_DIR)/.env.example
FRONTEND_ENV_EXAMPLE := $(FRONTEND_DIR)/.env.example

PYTHON ?= python3.10
PORT ?= 8000
LOG_LEVEL ?= info
RELOAD ?= 0

.PHONY: help ensure-env backend-install frontend-install bootstrap backend-dev frontend-dev dev

help:
	@echo "Targets:"
	@echo "  make bootstrap      Install backend + frontend deps"
	@echo "  make dev            Run backend and frontend together"
	@echo "  make backend-dev    Run backend only (FastAPI on PORT=$(PORT))"
	@echo "  make frontend-dev   Run frontend only (Next.js)"
	@echo ""
	@echo "Variables:"
	@echo "  PYTHON=python3.10   Python executable used when uv is unavailable"
	@echo "  PORT=8000           Backend port for backend-dev/dev"
	@echo "  LOG_LEVEL=info      Backend log level"
	@echo "  RELOAD=0            Set RELOAD=1 to enable uvicorn auto-reload"

ensure-env:
	@if [ ! -f "$(BACKEND_ENV)" ] && [ -f "$(BACKEND_ENV_EXAMPLE)" ]; then \
		cp "$(BACKEND_ENV_EXAMPLE)" "$(BACKEND_ENV)"; \
		echo "Created backend .env from .env.example"; \
	fi
	@if [ ! -f "$(FRONTEND_ENV)" ] && [ -f "$(FRONTEND_ENV_EXAMPLE)" ]; then \
		cp "$(FRONTEND_ENV_EXAMPLE)" "$(FRONTEND_ENV)"; \
		echo "Created frontend .env.local from .env.example"; \
	fi

backend-install:
	@cd "$(BACKEND_DIR)" && \
	if command -v uv >/dev/null 2>&1; then \
		uv sync; \
	else \
		$(PYTHON) -m venv .venv; \
		. .venv/bin/activate; \
		pip install -e .; \
	fi

frontend-install:
	@cd "$(FRONTEND_DIR)" && pnpm install

bootstrap: ensure-env backend-install frontend-install

backend-dev: ensure-env
	@cd "$(BACKEND_DIR)" && \
	set -a; [ -f .env ] && source .env; set +a; \
	if [ "$(RELOAD)" = "1" ]; then RELOAD_ARG="--reload"; else RELOAD_ARG=""; fi; \
	if command -v uv >/dev/null 2>&1; then \
		if uv run --no-sync python -c 'import uvicorn' >/dev/null 2>&1; then \
			uv run --no-sync python -m uvicorn app.main:app --host 127.0.0.1 --port $(PORT) --log-level $(LOG_LEVEL) $$RELOAD_ARG; \
		else \
			uv sync && uv run python -m uvicorn app.main:app --host 127.0.0.1 --port $(PORT) --log-level $(LOG_LEVEL) $$RELOAD_ARG; \
		fi; \
	elif [ -x .venv/bin/python ]; then \
		. .venv/bin/activate; \
		python -m uvicorn app.main:app --host 127.0.0.1 --port $(PORT) --log-level $(LOG_LEVEL) $$RELOAD_ARG; \
	else \
		echo "Backend deps not installed. Run 'make backend-install' first."; \
		exit 1; \
	fi

frontend-dev: ensure-env
	@cd "$(FRONTEND_DIR)" && pnpm dev

dev: ensure-env
	@trap 'kill 0' EXIT INT TERM; \
	$(MAKE) --no-print-directory backend-dev & \
	$(MAKE) --no-print-directory frontend-dev & \
	wait
