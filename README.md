# Service-Desk Ticket Triage: Conventional Automation vs Agentic Workflow

The same IT service-desk triage task built three ways and benchmarked on the same labelled tickets:

| Pipeline | What it is | Control flow decided by |
|---|---|---|
| **v1** | Regex + keyword rules + lookup tables | Code |
| **v1.5** | v1 + one LLM call when no rule matches | Code |
| **v2** | Deterministic shell around a ReAct agent with tools | The model (inside one loop) |

The goal is not to show that agents are better. It is to measure where the extra complexity pays for itself and where it doesn't.

- How a ticket moves through each pipeline: [docs/flows.md](docs/flows.md)
- Architecture diagrams: [docs/diagrams/](docs/diagrams/)

## Status

| Stage | Deliverable | State |
|---|---|---|
| 0 | Scaffold: contracts, taxonomy, config, logging, CI, module boundaries | done |
| 1 | v1 conventional pipeline + tests | done |
| 2 | Golden ticket set + benchmark harness (v1) | next |
| 3 | LLM client (record/replay) + v1.5 | |
| 4 | v2 agentic workflow | |
| 5 | Full benchmark report, ADRs, final diagrams | |

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and GNU make (Windows: `scoop install make`, run from Git Bash).

```bash
make install        # venv from uv.lock
make check          # lint, mypy --strict, import boundaries, unit + integration tests
make config-check   # validate config/*.yaml
make demo           # triage the five sample emails in data/samples with v1
make serve          # POST /tickets (web form) and GET /metrics on :8000
make docker-build && make docker-run
```

Queue mode: `uv run triage enqueue data/samples` then `uv run triage worker`.

v1 needs no model or API key. For v1.5 and v2, copy `.env.example` to `.env` and choose a provider.
Any OpenAI-compatible `/chat/completions` endpoint works: DeepSeek, OpenRouter, Ollama, vLLM.

## Layout

```
config/          behaviour: taxonomy, rules, prompts (versioned, reviewed in PRs)
src/triage/
  contracts/     Pydantic I/O models + TriagePipeline protocol (imports nothing internal)
  config.py      env settings + YAML loading, fail fast
  container.py   composition root: the only place objects are wired
  observability/ structured logs with correlation ids
  v1/ hybrid/ v2/ llm/ bench/
tests/unit/      deterministic tests: exact asserts, no network
docs/            flows, diagrams, ADRs
```

Module boundaries are enforced by import-linter (`[tool.importlinter]` in `pyproject.toml`). For example, `v1` cannot import any LLM code, and the benchmark only sees pipelines through the contract.
