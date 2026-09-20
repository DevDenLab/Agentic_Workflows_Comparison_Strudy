# Service-Desk Ticket Triage: Conventional Automation vs Agentic Workflow

The same IT service-desk triage task built three ways and benchmarked on the same labelled tickets:

| Pipeline | What it is | Control flow decided by |
|---|---|---|
| **v1** | Regex + keyword rules + lookup tables | Code |
| **v1.5** | v1 + one LLM call when no rule matches | Code |
| **v2** | Deterministic shell around a ReAct agent with tools | The model (inside one loop) |

The goal is not to show that agents are better. It is to measure where the extra complexity pays for itself and where it doesn't. On this task it mostly doesn't — see [Results](#results).

### Start here

**[`notebooks/service_desk_triage.ipynb`](notebooks/service_desk_triage.ipynb)** is the guided tour:
all three pipelines built up step by step with diagrams, worked examples and the full benchmark. It
runs offline from committed cassettes — no API key, no network, no cost, same numbers every time.

```bash
make notebook       # open it in JupyterLab
```

Or read the source directly:

- How a ticket moves through each pipeline: [docs/flows.md](docs/flows.md)
- How every label was decided, and the scoring rules: [docs/labelling-guide.md](docs/labelling-guide.md)
- Architecture diagrams: [docs/diagrams/](docs/diagrams/)

## Status

| Stage | Deliverable | State |
|---|---|---|
| 0 | Scaffold: contracts, taxonomy, config, logging, CI, module boundaries | done |
| 1 | v1 conventional pipeline + tests | done |
| 2 | Golden ticket set (150, human-reviewed) + benchmark harness | done |
| 3 | LLM client (record/replay) + v1.5 hybrid | done |
| 4 | v2 agentic workflow: guardrail, tools, critic, confidence gate | done |
| 5 | ADRs and final architecture diagrams | in progress |

## Results

150 human-labelled tickets, 3 runs each. Full tables in
[reports/benchmark/](reports/benchmark/), the reasoning behind them in the notebook.

| | v1 rules | v1.5 hybrid | v2 agentic |
|---|---|---|---|
| Decision accuracy | 56.0% | **70.7%** | 40.0% |
| …in-distribution | **98.0%** | **98.0%** | 52.0% |
| False-confident rate (lower better) | 20.4% | 29.3% | **12.2%** |
| Escalation recall (must-escalate) | 52.6% | 0.0% | **89.5%** |
| Tokens per ticket | **0** | 330 | 5,024 |

Three findings worth stating plainly:

- **v1.5 is the most accurate and the most dangerous.** Its forced tool call has no "I don't know",
  so it auto-resolved *every* must-escalate ticket — including a request to disable a user's MFA.
- **v1 beats v2 on accuracy by 16 points using no model at all**, and ties it in-distribution at
  98%. If your tickets are mostly well-phrased, rules are not just adequate — they are better.
- **v2's accuracy is low because it escalates correct answers.** 57 of its 101 escalations carried
  a draft that exactly matched the human label; trusting those would have put it at 78%. The
  critic is over-strict, and it has deliberately not been re-tuned after seeing the scores.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and GNU make (Windows: `scoop install make`, run from Git Bash).

```bash
make install        # venv from uv.lock
make notebook       # the guided tour of all three pipelines (offline, no API key)
make check          # lint, mypy --strict, import boundaries, unit + integration tests
make config-check   # validate config/*.yaml
make demo           # triage the five sample emails in data/samples with v1
make serve          # POST /tickets (web form) and GET /metrics on :8000
make docker-build && make docker-run
```

Queue mode: `uv run triage enqueue data/samples` then `uv run triage worker`.

### Benchmark

```bash
make review-sheet   # golden set -> reports/label-review.csv for human label review
make bench          # grade v1 -> reports/benchmark/v1_conventional/ (summary.md, charts, per-run results)
make bench-check    # what CI runs: fail if accuracy or escalation recall drops, or false-confident rises

uv run triage bench --pipeline v1.5 --llm-mode replay   # v1.5 and v2 replay committed cassettes,
uv run triage bench --pipeline v2   --llm-mode replay   # so CI grades them with no key and no bill
```

`triage bench` refuses to run until every `data/golden/*.yaml` names a reviewer (`reviewed_by`,
`reviewed_on`); `--allow-draft` overrides that for local experiments. Scoring rules are fixed in
[docs/labelling-guide.md](docs/labelling-guide.md) §9. Intervals are 95% Wilson intervals whose
sample size is the number of tickets, so repeated runs never make them look tighter than they are.

v1 needs no model or API key. For v1.5 and v2, copy `.env.example` to `.env` and choose a provider.
Any OpenAI-compatible `/chat/completions` endpoint works: DeepSeek, OpenRouter, Ollama, vLLM.

## Layout

```
notebooks/       the guided tour (service_desk_triage.ipynb) + its display helpers
config/          behaviour: taxonomy, rules, prompts (versioned, reviewed in PRs)
data/
  golden/        150 human-labelled tickets, split in_dist / ood / adversarial
  cassettes/     613 recorded LLM responses, so v1.5 and v2 replay offline
  runbooks/ history/ cmdb/ samples/
src/triage/
  contracts/     Pydantic I/O models + TriagePipeline protocol (imports nothing internal)
  config.py      env settings + YAML loading, fail fast
  container.py   composition root: the only place objects are wired
  observability/ structured logs with correlation ids
  v1/            the twelve conventional steps
  hybrid/        v1.5: v1 + one forced LLM call at the rule-miss node
  v2/            guardrail, budget, tools, agent loop, critic, confidence gate
  llm/ bench/
tests/           323 tests — unit (exact asserts, no network) + integration
docs/            flows, labelling guide, diagrams, ADRs
reports/         benchmark output: summaries, charts, per-case rows
```

Module boundaries are enforced by import-linter (`[tool.importlinter]` in `pyproject.toml`). For example, `v1` cannot import any LLM code, and the benchmark only sees pipelines through the contract.
