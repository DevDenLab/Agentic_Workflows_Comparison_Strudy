"""Benchmark outputs: per-run results, a machine-readable summary, a markdown report, and the
regression check CI runs against a committed baseline."""

import json
from collections.abc import Iterable, Sequence
from pathlib import Path

from triage.bench.scoring import BenchmarkSummary, CaseRun, CaseScore, GroupSummary, Proportion

RESULTS_FILE = "results.jsonl"
SUMMARY_JSON = "summary.json"
SUMMARY_MD = "summary.md"

_RATE_ROWS: tuple[tuple[str, str], ...] = (
    ("Decision accuracy", "decision_accuracy"),
    ("Category accuracy", "category_accuracy"),
    ("Priority accuracy", "priority_accuracy"),
    ("Routing accuracy", "routing_accuracy"),
    ("Auto-resolution rate", "auto_resolution_rate"),
    ("Escalation rate", "escalation_rate"),
    ("Accuracy when auto-resolved", "accuracy_when_auto_resolved"),
    ("**False-confident rate**", "false_confident_rate"),
    ("Escalation recall (must-escalate cases)", "escalation_recall"),
    ("Stable across runs", "stable_tickets"),
)


def write_results(scored: Sequence[tuple[CaseRun, CaseScore]], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / RESULTS_FILE
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for case_run, score in scored:
            result = case_run.result
            record = {
                "case_id": score.case_id,
                "split": score.split.value,
                "subtype": score.subtype.value,
                "run": score.run,
                "expected": score.expected,
                "got": score.got,
                "decided_by": result.decided_by.value if result.decided_by else None,
                "escalation_reason": result.escalation_reason,
                "correct": score.correct,
                "confident_error": score.confident_error,
                "category_correct": score.category_correct,
                "priority_correct": score.priority_correct,
                "routing_correct": score.routing_correct,
                "latency_ms": round(score.latency_ms, 3),
                "tokens": score.tokens,
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def write_summary(summary: BenchmarkSummary, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / SUMMARY_JSON).write_text(summary.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (out_dir / SUMMARY_MD).write_text(render_markdown(summary), encoding="utf-8")


def load_summary(path: Path) -> BenchmarkSummary:
    return BenchmarkSummary.model_validate_json(path.read_text(encoding="utf-8"))


def format_rate(proportion: Proportion) -> str:
    """'66.7% (21–94)': the value, then its 95% interval in percentage points."""
    if proportion.value is None or proportion.ci_low is None or proportion.ci_high is None:
        return "—"
    low, high = proportion.ci_low * 100, proportion.ci_high * 100
    return f"{proportion.value:.1%} ({low:.0f}–{high:.0f})"


def _format_ms(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}"


def _row(label: str, cells: Iterable[str]) -> str:
    return f"| {label} | " + " | ".join(cells) + " |"


def _rate_cell(group: GroupSummary, attribute: str) -> str:
    if attribute == "stable_tickets" and group.runs < 2:
        return "— (1 run)"
    return format_rate(getattr(group, attribute))


def _table(groups: Sequence[GroupSummary]) -> list[str]:
    lines = [
        _row("Metric", (group.name for group in groups)),
        "|---|" + "---:|" * len(groups),
        _row("Tickets", (str(group.tickets) for group in groups)),
    ]
    lines += [
        _row(label, (_rate_cell(group, attribute) for group in groups))
        for label, attribute in _RATE_ROWS
    ]
    lines += [
        _row("p50 latency (ms)", (_format_ms(group.latency_p50_ms) for group in groups)),
        _row("p95 latency (ms)", (_format_ms(group.latency_p95_ms) for group in groups)),
        _row("Tokens per ticket", (f"{group.tokens_per_ticket:.0f}" for group in groups)),
    ]
    return lines


def render_markdown(summary: BenchmarkSummary) -> str:
    errors = summary.confident_errors
    lines = [
        f"# Benchmark: `{summary.pipeline}`",
        "",
        f"{summary.overall.tickets} golden tickets × {summary.repeats} runs. "
        f"Golden set fingerprint `{summary.golden_fingerprint}`.",
        "",
        "Rates show the value with its 95% Wilson interval in brackets; the interval's sample size "
        "is the number of tickets, not ticket-runs. Scoring follows `docs/labelling-guide.md` §9: "
        "escalating a ticket that could have been auto-resolved earns no credit, and "
        "auto-resolving a ticket that must be escalated is a confident error.",
        "",
        "## By split",
        "",
        *_table([*summary.splits.values(), summary.overall]),
        "",
    ]
    if summary.adversarial_subtypes:
        lines += [
            "## Adversarial subtypes",
            "",
            "Ten tickets each, so the intervals are wide.",
            "",
            *_table(list(summary.adversarial_subtypes.values())),
            "",
        ]
    lines += [f"## Confident errors ({len(errors)} ticket{'' if len(errors) == 1 else 's'})", ""]
    if errors:
        lines += ["| Ticket | Subtype | Expected | Got |", "|---|---|---|---|"]
        lines += [f"| {e.case_id} | {e.subtype} | {e.expected} | {e.got} |" for e in errors]
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def regressions(
    current: BenchmarkSummary, baseline: BenchmarkSummary, tolerance: float
) -> list[str]:
    """Differences that should fail CI. An empty list means no regression."""
    if current.pipeline != baseline.pipeline:
        raise ValueError(f"baseline is for {baseline.pipeline}, not {current.pipeline}")
    if current.golden_fingerprint != baseline.golden_fingerprint:
        return [
            "the golden set changed since the baseline was recorded; "
            "review the new numbers and commit a new baseline"
        ]

    pairs = {"all": (current.overall, baseline.overall)}
    pairs |= {
        name: (group, baseline.splits[name])
        for name, group in current.splits.items()
        if name in baseline.splits
    }
    problems: list[str] = []
    for name, (now, before) in pairs.items():
        for attribute, worse_when_higher in (
            ("decision_accuracy", False),
            ("escalation_recall", False),
            ("false_confident_rate", True),
        ):
            new, old = getattr(now, attribute).value, getattr(before, attribute).value
            if new is None or old is None:
                continue
            change = new - old if worse_when_higher else old - new
            if change > tolerance:
                problems.append(f"{name}: {attribute} moved from {old:.1%} to {new:.1%}")
    return problems
