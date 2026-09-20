"""Plumbing for `service_desk_triage.ipynb` — wiring and pretty-printing, no triage logic.

Everything that decides anything lives in `src/triage/`. This module only does three things the
notebook needs and the library rightly does not provide:

  * `Lab.open()` — build all three pipelines against the committed cassettes, so the notebook runs
    offline, deterministically, and without an API key.
  * `message()` — turn a golden case into an `InboundMessage`, exactly the way the benchmark does,
    so the recorded cassettes match.
  * `show_*` / `table` — render a `TriageResult`, an audit trail or a summary as HTML.

It deliberately sits outside `src/triage/` (import-linter's `root_package`), because notebook
display helpers are not part of the system under test.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

from IPython.display import HTML, display
from pydantic import SecretStr

from triage.bench.golden import GoldenCase, GoldenSet, load_golden_set
from triage.bench.messages import to_message
from triage.bench.runner import BenchConfig, load_bench_config
from triage.clock import SystemClock
from triage.config import Settings
from triage.container import (
    Container,
    build_agent,
    build_container,
    build_hybrid,
    build_llm_client,
    build_v1,
)
from triage.contracts import AuditEvent, InboundMessage, TriagePipeline, TriageResult
from triage.llm.client import LlmClient
from triage.v1.extractor import Extractor
from triage.v1.parser import Parser
from triage.v1.rule_engine import RuleEngine
from triage.v2.agent import Orchestrator
from triage.v2.critic import GroundingCritic
from triage.v2.guardrail import PiiGuardrail, RedactedText
from triage.v2.settings import V2Config, load_v2_config
from triage.v2.tools import (
    ApplyRulesTool,
    CmdbLookupTool,
    KbSearchTool,
    SimilarTicketsTool,
    Tool,
    load_history_index,
    load_runbook_index,
)

__all__ = [
    "AgentBits",
    "Lab",
    "bootstrap",
    "find_root",
    "note",
    "show_audit",
    "show_message",
    "show_result",
    "table",
]


def find_root(start: Path | None = None) -> Path:
    """The project root, whether the kernel started in notebooks/ or the repo root."""
    start = (start or Path.cwd()).resolve()
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "config").is_dir():
            return candidate
    raise RuntimeError(f"no project root above {start} (looked for pyproject.toml + config/)")


def bootstrap(start: Path | None = None) -> Path:
    """Make `triage` and `nbsupport` importable and `config/`, `data/` resolvable.

    Called from the notebook's first cell so it works from any kernel and any working directory:
    `src/` goes on `sys.path` (so no editable install is required), and the process moves to the
    project root (so `Settings`' relative default paths — `config`, `data` — point at the repo).
    """
    root = find_root(start)
    for extra in (root / "src", root / "notebooks"):
        if extra.is_dir() and str(extra) not in sys.path:
            sys.path.insert(0, str(extra))
    if Path.cwd().resolve() != root:
        os.chdir(root)
    return root


def _cassette_model(cassette_dir: Path) -> str:
    """The model name the cassettes were recorded against.

    Read from a cassette rather than from .env on purpose: the cassette key is a hash of the whole
    request payload, and the model name is part of that payload. Pointing TRIAGE_MODEL at a
    different model would silently miss every cassette. Reading it back cannot drift.
    """
    recordings = sorted(cassette_dir.glob("*.json"))
    if not recordings:
        raise RuntimeError(f"no cassettes in {cassette_dir}")
    payload = json.loads(recordings[0].read_text(encoding="utf-8"))
    return str(payload["request"]["model"])


@dataclass(frozen=True, slots=True)
class AgentBits:
    """v2's moving parts for one ticket, assembled the way `build_agent` assembles them.

    The pipeline does this internally and hands back only a `TriageResult`. Section 3 needs to stop
    between the steps, so it builds the same objects here and drives them by hand.
    """

    subject: str
    """Redacted — what the model is actually shown."""
    text: str
    guardrail: PiiGuardrail
    orchestrator: Orchestrator
    tools: list[Tool]
    critic: GroundingCritic
    config: V2Config


@dataclass(frozen=True, slots=True)
class Lab:
    """The notebook's world: config, golden set, and one of each pipeline."""

    root: Path
    settings: Settings
    container: Container
    golden: GoldenSet
    bench: BenchConfig
    v1: TriagePipeline
    v15: TriagePipeline
    v2: TriagePipeline
    replay: bool
    agent_client: LlmClient

    @classmethod
    def open(cls, root: Path | None = None, *, live: bool = False) -> Lab:
        """Build all three pipelines.

        `live=False` (the default) replays the committed cassettes: no key, no network, no cost,
        and the same answer every run. `live=True` calls the real provider and needs LLM_BASE_URL,
        LLM_API_KEY and TRIAGE_MODEL in .env.
        """
        root = bootstrap(root)
        cassettes = root / "data" / "cassettes"
        state = root / ".notebook-state"

        if live:
            from_env = Settings()
            if not from_env.llm_configured:
                raise RuntimeError(
                    "live=True needs LLM_BASE_URL, LLM_API_KEY and TRIAGE_MODEL in .env"
                )
            base = from_env
            mode = "replay_or_record"
        else:
            # Placeholders: in replay mode the inner transport is never called, but the composition
            # root still validates that the three settings are present.
            base = Settings(
                llm_base_url="https://replay.invalid/v1",
                llm_api_key=SecretStr("replay-only-never-sent"),
                triage_model=_cassette_model(cassettes / "v2_agentic"),
                critic_model=None,
            )
            mode = "replay"

        clock = SystemClock()
        pipelines: dict[str, TriagePipeline] = {}
        agent_client: LlmClient | None = None
        for name in ("v1", "v1_5_hybrid", "v2_agentic"):
            # Each pipeline gets its own wiped state directory. Sharing one would give them a
            # shared idempotency store, and the second pipeline to see a ticket would call it a
            # duplicate — a benchmark artefact, not a triage decision.
            run_dir = state / name
            shutil.rmtree(run_dir, ignore_errors=True)
            settings = base.model_copy(update={"var_dir": run_dir, "log_level": "WARNING"})
            container = build_container(settings, clock=clock)
            if name == "v1":
                pipelines[name] = build_v1(container).pipeline
            elif name == "v1_5_hybrid":
                client = build_llm_client(settings, clock, mode=mode, cassette_subdir="v1_5_hybrid")
                pipelines[name] = build_hybrid(container, client).pipeline
            else:
                agent_client = build_llm_client(
                    settings, clock, mode=mode, cassette_subdir="v2_agentic"
                )
                pipelines[name] = build_agent(container, agent_client, agent_client).pipeline

        if agent_client is None:  # unreachable: the loop always builds the v2 client
            raise RuntimeError("the agent client was never constructed")
        settings = base.model_copy(update={"var_dir": state / "shared", "log_level": "WARNING"})
        container = build_container(settings, clock=clock)
        return cls(
            root=root,
            settings=settings,
            container=container,
            golden=load_golden_set(settings.data_dir / "golden"),
            bench=load_bench_config(settings.config_dir),
            v1=pipelines["v1"],
            v15=pipelines["v1_5_hybrid"],
            v2=pipelines["v2_agentic"],
            replay=not live,
            agent_client=agent_client,
        )

    # -- v2 internals -------------------------------------------------------------

    def agent_bits(self, case_id: str) -> AgentBits:
        """Assemble v2's parts for one ticket so section 3 can step through them by hand."""
        from jinja2 import Environment, FileSystemLoader, StrictUndefined

        from triage.container import init_cmdb
        from triage.v1.cmdb import SqliteCmdb

        settings, config, v1 = self.settings, self.container.config, self.container.v1
        v2 = load_v2_config(settings.config_dir)

        message = self.message(case_id)
        text = Parser(v1.parsing.parser).parse(message)
        guardrail = PiiGuardrail()
        redacted: RedactedText = guardrail.redact(message.subject, text)

        env = Environment(
            loader=FileSystemLoader(settings.config_dir / "prompts"),
            undefined=StrictUndefined,
            autoescape=False,  # noqa: S701 - a prompt string, not HTML
        )
        system_prompt = env.get_template("agent_system.j2").render(
            organisation=config.app.organisation, categories=config.taxonomy.categories
        )

        tools: list[Tool] = [
            KbSearchTool(load_runbook_index(settings.data_dir / "runbooks")),
            SimilarTicketsTool(
                load_history_index(settings.data_dir / "history" / "resolved.jsonl")
            ),
            CmdbLookupTool(SqliteCmdb(init_cmdb(self.container)), guardrail),
            ApplyRulesTool(RuleEngine(v1.rules), redacted.subject, redacted.text),
        ]
        return AgentBits(
            subject=redacted.subject,
            text=redacted.text,
            guardrail=guardrail,
            orchestrator=Orchestrator(self.agent_client, config.taxonomy, v2.agent, system_prompt),
            tools=tools,
            critic=GroundingCritic(self.agent_client, v2.critic),
            config=v2,
        )

    def parsed(self, case_id: str) -> tuple[str, str]:
        """(subject, parsed text) for a golden case — what the decision layer sees."""
        message = self.message(case_id)
        v1 = self.container.v1
        return message.subject, Parser(v1.parsing.parser).parse(message)

    def extracted(self, case_id: str):
        subject, text = self.parsed(case_id)
        return Extractor(self.container.v1.parsing.extractor).extract(subject, text)

    # -- golden set ---------------------------------------------------------------

    def case(self, case_id: str) -> GoldenCase:
        for case in self.golden.cases:
            if case.id == case_id:
                return case
        raise KeyError(f"no golden case {case_id!r}")

    def message(self, case_id: str, *, unique: bool = True) -> InboundMessage:
        """The `InboundMessage` a real intake would have produced for this golden case.

        `unique=True` appends a counter to the message id so re-running a notebook cell is not
        treated as a duplicate submission. The id is an email header, stripped before the text
        ever reaches a prompt, so this never changes what the model sees or which cassette is hit.
        """
        base = to_message(
            self.case(case_id),
            received_at=self.bench.received_at,
            service_desk_address=self.bench.service_desk_address,
        )
        if not unique:
            return base
        _COUNTER[case_id] = _COUNTER.get(case_id, 0) + 1
        suffix = f".n{_COUNTER[case_id]}"
        message_id = (
            base.message_id.replace("@", f"{suffix}@", 1)
            if "@" in base.message_id
            else base.message_id + suffix
        )
        return base.model_copy(update={"message_id": message_id})

    def compare(self, case_id: str) -> dict[str, TriageResult]:
        """Run one ticket through all three pipelines."""
        return {
            pipeline.name: pipeline.triage(self.message(case_id))
            for pipeline in (self.v1, self.v15, self.v2)
        }


_COUNTER: dict[str, int] = {}


# -- display ----------------------------------------------------------------------

_CSS = """
<style>
.nbt { border-collapse: collapse; font-size: 13px; margin: 6px 0 12px; width: 100%; }
.nbt th, .nbt td { border: 1px solid rgba(128,128,128,.35); padding: 5px 9px; text-align: left;
  vertical-align: top; }
.nbt th { background: rgba(128,128,128,.14); font-weight: 600; }
.nbt td.num { text-align: right; font-variant-numeric: tabular-nums; }
.nbt code { font-size: 12px; }
.nbpill { display:inline-block; padding:1px 8px; border-radius:10px; font-size:12px;
  font-weight:600; border:1px solid; }
.nb-auto { background:#ddf0e3; color:#10381f; border-color:#2f7d4f; }
.nb-esc  { background:#fbe1e1; color:#5c1512; border-color:#b3322e; }
.nb-dup  { background:#eceff3; color:#3a4654; border-color:#7c8a9b; }
.nbnote { border-left: 3px solid #c1651a; background: rgba(193,101,26,.10); padding: 8px 12px;
  margin: 10px 0; font-size: 13px; border-radius: 0 4px 4px 0; }
</style>
"""

_OUTCOME_CLASS = {
    "auto_resolved": "nb-auto",
    "human_review": "nb-esc",
    "duplicate": "nb-dup",
    "dead_letter": "nb-dup",
}


def _pill(outcome: str) -> str:
    return f"<span class='nbpill {_OUTCOME_CLASS.get(outcome, 'nb-dup')}'>{escape(outcome)}</span>"


def table(rows: list[dict[str, Any]], caption: str = "") -> None:
    """Render a list of dicts as an HTML table. Values starting with '<' pass through as HTML."""
    if not rows:
        display(HTML(_CSS + "<em>(nothing to show)</em>"))
        return
    headers = list(rows[0])
    head = "".join(f"<th>{escape(str(h))}</th>" for h in headers)
    body = ""
    for row in rows:
        cells = ""
        for header in headers:
            value = row.get(header, "")
            rendered = str(value)
            if not rendered.startswith("<"):
                rendered = escape(rendered)
            numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
            cells += f"<td class='{'num' if numeric else ''}'>{rendered}</td>"
        body += f"<tr>{cells}</tr>"
    cap = (
        f"<caption style='text-align:left;font-weight:600;padding:4px 0'>"
        f"{escape(caption)}</caption>"
        if caption
        else ""
    )
    display(
        HTML(
            f"{_CSS}<table class='nbt'>{cap}"
            f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
        )
    )


def note(text: str) -> None:
    display(HTML(f"{_CSS}<div class='nbnote'>{text}</div>"))


def show_message(message: InboundMessage, *, body_chars: int = 400) -> None:
    table(
        [
            {"field": "message_id", "value": message.message_id},
            {"field": "channel", "value": message.channel.value},
            {"field": "sender", "value": message.sender},
            {"field": "subject", "value": message.subject},
            {
                "field": "raw_body",
                "value": f"<pre style='margin:0;white-space:pre-wrap;font-size:12px'>"
                f"{escape(message.raw_body[:body_chars])}"
                f"{'…' if len(message.raw_body) > body_chars else ''}</pre>",
            },
        ],
        caption="InboundMessage — exactly what intake received",
    )


def show_result(result: TriageResult, *, draft_chars: int = 0) -> None:
    decision = result.decision
    rows: list[dict[str, Any]] = [
        {"field": "pipeline", "value": result.pipeline},
        {"field": "outcome", "value": _pill(result.outcome.value)},
        {"field": "decided_by", "value": result.decided_by.value if result.decided_by else "—"},
    ]
    if decision is not None:
        rows += [
            {"field": "category", "value": decision.category},
            {"field": "priority", "value": decision.priority.value},
            {"field": "assignment_group", "value": decision.assignment_group},
            {"field": "confidence", "value": f"{decision.confidence:.2f}"},
            {
                "field": "citations",
                "value": ", ".join(c.source_id for c in decision.citations) or "—",
            },
        ]
    if result.escalation_reason:
        rows.append({"field": "escalation_reason", "value": result.escalation_reason})
    usage = result.usage
    rows += [
        {"field": "latency_ms", "value": f"{usage.latency_ms:.0f}"},
        {
            "field": "tokens",
            "value": f"{usage.prompt_tokens + usage.completion_tokens} "
            f"({usage.llm_calls} call{'s' if usage.llm_calls != 1 else ''}, "
            f"{usage.agent_steps} agent step{'s' if usage.agent_steps != 1 else ''})",
        },
    ]
    if draft_chars and decision is not None:
        rows.append(
            {
                "field": "draft_response",
                "value": f"<pre style='margin:0;white-space:pre-wrap;font-size:12px'>"
                f"{escape(decision.draft_response[:draft_chars])}"
                f"{'…' if len(decision.draft_response) > draft_chars else ''}</pre>",
            }
        )
    table(rows, caption=f"TriageResult — {result.pipeline}")


def show_audit(result: TriageResult, *, detail: bool = True) -> None:
    """The audit trail: every component that ran, in order, with what it decided."""
    rows = []
    for index, event in enumerate(result.audit, start=1):
        rows.append(
            {
                "#": index,
                "component": event.component,
                "event": event.event,
                "detail": _detail(event) if detail else "",
            }
        )
    table(rows, caption=f"Audit trail — {len(result.audit)} steps")


def _detail(event: AuditEvent) -> str:
    if not event.detail:
        return "—"
    parts = []
    for key, value in event.detail.items():
        if value in (None, [], {}, ""):
            continue
        rendered = json.dumps(value) if isinstance(value, (list, dict)) else str(value)
        if len(rendered) > 90:
            rendered = rendered[:90] + "…"
        parts.append(f"<code>{escape(key)}={escape(rendered)}</code>")
    return " ".join(parts) or "—"
