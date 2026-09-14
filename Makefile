# Every target goes through uv. Works in Git Bash on Windows and any shell on Linux/macOS.
.DEFAULT_GOAL := help
SHELL := bash

# On Windows, keep the virtualenv out of OneDrive-synced folders.
ifdef LOCALAPPDATA
export UV_PROJECT_ENVIRONMENT ?= $(subst \,/,$(LOCALAPPDATA))/service-desk-triage/venv
endif

.PHONY: help install lint format typecheck imports test-unit test-integration test check \
	config-check review-sheet demo serve docker-build docker-run clean

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-14s %s\n", $$1, $$2}'

install: ## Create the venv from the lockfile
	uv sync --locked

lint: ## Ruff lint + format check
	uv run ruff check .
	uv run ruff format --check .

format: ## Apply ruff fixes and formatting
	uv run ruff check --fix .
	uv run ruff format .

typecheck: ## mypy --strict over src and tests
	uv run mypy

imports: ## Enforce module boundaries ([tool.importlinter] in pyproject.toml)
	uv run lint-imports

test-unit: ## One component at a time: exact asserts, no network
	uv run pytest tests/unit

test-integration: ## v1 end to end on real SQLite files in a temp dir
	uv run pytest tests/integration

test: ## All deterministic tests, with coverage
	uv run pytest tests/unit tests/integration --cov --cov-report=term-missing

check: lint typecheck imports test ## Everything CI runs

config-check: ## Validate every config file
	uv run triage config-check

review-sheet: ## Export the golden set to reports/label-review.csv for label review
	uv run triage review-sheet

demo: ## Triage the sample emails with v1
	uv run triage run data/samples

serve: ## Web-form intake (POST /tickets) and /metrics on :8000
	uv run uvicorn triage.api:create_app --factory --port 8000

docker-build: ## Build the container image
	docker build -t service-desk-triage:dev .

docker-run: ## Run the container image on :8000
	docker run --rm -p 8000:8000 service-desk-triage:dev

clean: ## Remove tool caches
	rm -rf .mypy_cache .ruff_cache .pytest_cache .coverage htmlcov
