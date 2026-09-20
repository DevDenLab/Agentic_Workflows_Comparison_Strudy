"""Scoring rules, exactly as fixed in docs/labelling-guide.md section 9, and their aggregation.

Everything here is a pure function of typed inputs, so it is covered by ordinary unit tests.
"""

import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, computed_field

from triage.bench.golden import GoldenCase, Handling, Split, Subtype
from triage.contracts import Outcome, TriageResult

Z_95 = 1.959963984540054


@dataclass(frozen=True, slots=True)
class CaseRun:
    case: GoldenCase
    run: int
    result: TriageResult


@dataclass(frozen=True, slots=True)
class CaseScore:
    case_id: str
    split: Split
    subtype: Subtype
    run: int
    handling: Handling
    outcome: Outcome
    auto_resolved: bool
    escalated: bool
    category_correct: bool | None
    """None for escalate-handling cases, which are judged on escalation alone."""
    priority_correct: bool | None
    routing_correct: bool | None
    correct: bool
    confident_error: bool
    latency_ms: float
    tokens: int
    signature: tuple[str | None, ...]
    """What the determinism check compares across runs: outcome, category, priority, group."""
    expected: str
    got: str


@dataclass(frozen=True, slots=True)
class _Reading:
    category: str
    assignment_group: str
    priority: str


def score_case(case_run: CaseRun) -> CaseScore:
    case, result = case_run.case, case_run.result
    auto_resolved = result.outcome is Outcome.AUTO_RESOLVED
    escalated = result.outcome is Outcome.HUMAN_REVIEW
    decision = result.decision

    category: bool | None = None
    priority: bool | None = None
    routing: bool | None = None
    if case.label.handling is Handling.ESCALATE:
        correct = escalated
    elif auto_resolved and decision is not None:
        reading = _reading_for(case, decision.category)
        category = decision.category == reading.category
        priority = decision.priority.value == reading.priority
        routing = decision.assignment_group == reading.assignment_group
        correct = category and priority and routing
    else:
        category = priority = routing = False
        correct = False

    return CaseScore(
        case_id=case.id,
        split=case.split,
        subtype=case.subtype,
        run=case_run.run,
        handling=case.label.handling,
        outcome=result.outcome,
        auto_resolved=auto_resolved,
        escalated=escalated,
        category_correct=category,
        priority_correct=priority,
        routing_correct=routing,
        correct=correct,
        confident_error=auto_resolved and not correct,
        latency_ms=result.usage.latency_ms,
        tokens=result.usage.prompt_tokens + result.usage.completion_tokens,
        signature=_signature(result),
        expected=_describe_expected(case),
        got=_describe_result(result),
    )


def _reading_for(case: GoldenCase, chosen_category: str) -> _Reading:
    """The labelled reading whose category the pipeline chose (guide A1), else the primary one."""
    label = case.label
    if label.category is None or label.assignment_group is None or label.priority is None:
        raise ValueError(f"{case.id}: an auto-handling case must be fully labelled")
    readings = [_Reading(label.category, label.assignment_group, label.priority.value)]
    readings += [
        _Reading(alt.category, alt.assignment_group, alt.priority.value)
        for alt in label.alternatives
    ]
    return next((r for r in readings if r.category == chosen_category), readings[0])


def _signature(result: TriageResult) -> tuple[str | None, ...]:
    decision = result.decision
    if decision is None:
        return (result.outcome.value, None, None, None)
    return (
        result.outcome.value,
        decision.category,
        decision.priority.value,
        decision.assignment_group,
    )


def _describe_expected(case: GoldenCase) -> str:
    label = case.label
    labels = (
        f"{label.category} / {label.priority} / {label.assignment_group}"
        if label.determinable
        else "undeterminable"
    )
    return f"escalate ({labels})" if label.handling is Handling.ESCALATE else labels


def _describe_result(result: TriageResult) -> str:
    decision = result.decision
    if decision is None:
        return result.outcome.value
    return (
        f"{result.outcome.value}: {decision.category} / {decision.priority.value} / "
        f"{decision.assignment_group}"
    )


# --- statistics -------------------------------------------------------------------


def wilson_interval(p: float, n: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval for a proportion `p` observed on `n` independent samples."""
    if n <= 0:
        raise ValueError("n must be positive")
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half_width = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, centre - half_width), min(1.0, centre + half_width)


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolated percentile, `q` in [0, 1]. None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


class _SummaryModel(BaseModel):
    # extra="ignore" so a summary.json (which includes computed fields) loads back as a baseline.
    model_config = ConfigDict(frozen=True, extra="ignore")


class Proportion(_SummaryModel):
    """successes / total, with a 95% Wilson interval.

    The interval's sample size is the number of distinct tickets, not case-runs: running the same
    ticket again is not a new independent sample, so repeats must not make the interval narrower.
    """

    successes: int
    total: int
    tickets: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def value(self) -> float | None:
        return self.successes / self.total if self.total else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ci_low(self) -> float | None:
        return self._interval()[0] if self.value is not None else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ci_high(self) -> float | None:
        return self._interval()[1] if self.value is not None else None

    def _interval(self) -> tuple[float, float]:
        if self.value is None:
            raise ValueError("an empty proportion has no interval")
        return wilson_interval(self.value, self.tickets)


def _proportion(pool: Sequence[CaseScore], hit: Callable[[CaseScore], bool]) -> Proportion:
    return Proportion(
        successes=sum(1 for score in pool if hit(score)),
        total=len(pool),
        tickets=len({score.case_id for score in pool}),
    )


class GroupSummary(_SummaryModel):
    name: str
    tickets: int
    runs: int
    decision_accuracy: Proportion
    """Correct outcome over all cases. Escalating an auto case earns no credit."""
    category_accuracy: Proportion
    priority_accuracy: Proportion
    routing_accuracy: Proportion
    """Field accuracies over auto-handling cases; an escalated case counts as not correct."""
    auto_resolution_rate: Proportion
    escalation_rate: Proportion
    accuracy_when_auto_resolved: Proportion
    false_confident_rate: Proportion
    """Confident errors over auto-resolved cases. Equals 1 - accuracy_when_auto_resolved."""
    escalation_recall: Proportion
    """Escalate-handling cases that were escalated."""
    unexpected_outcomes: int
    """Duplicate or dead-letter outcomes: infrastructure problems, not triage decisions."""
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    tokens_per_ticket: float
    stable_tickets: Proportion
    """Tickets whose outcome, category, priority and group were identical in every run."""


class ErrorExample(_SummaryModel):
    case_id: str
    split: str
    subtype: str
    expected: str
    got: str


class BenchmarkSummary(_SummaryModel):
    pipeline: str
    repeats: int
    golden_fingerprint: str
    overall: GroupSummary
    splits: dict[str, GroupSummary]
    adversarial_subtypes: dict[str, GroupSummary]
    confident_errors: list[ErrorExample]
    """One entry per ticket that was a confident error in at least one run (first occurrence)."""


def summarise_group(name: str, scores: Sequence[CaseScore]) -> GroupSummary:
    auto_handling = [s for s in scores if s.handling is Handling.AUTO]
    auto_resolved = [s for s in scores if s.auto_resolved]
    must_escalate = [s for s in scores if s.handling is Handling.ESCALATE]
    latencies = [s.latency_ms for s in scores]

    signatures: dict[str, set[tuple[str | None, ...]]] = defaultdict(set)
    for score in scores:
        signatures[score.case_id].add(score.signature)
    stable = sum(1 for seen in signatures.values() if len(seen) == 1)

    return GroupSummary(
        name=name,
        tickets=len(signatures),
        runs=len({s.run for s in scores}),
        decision_accuracy=_proportion(scores, lambda s: s.correct),
        category_accuracy=_proportion(auto_handling, lambda s: s.category_correct is True),
        priority_accuracy=_proportion(auto_handling, lambda s: s.priority_correct is True),
        routing_accuracy=_proportion(auto_handling, lambda s: s.routing_correct is True),
        auto_resolution_rate=_proportion(scores, lambda s: s.auto_resolved),
        escalation_rate=_proportion(scores, lambda s: s.escalated),
        accuracy_when_auto_resolved=_proportion(auto_resolved, lambda s: s.correct),
        false_confident_rate=_proportion(auto_resolved, lambda s: s.confident_error),
        escalation_recall=_proportion(must_escalate, lambda s: s.escalated),
        unexpected_outcomes=sum(
            1 for s in scores if s.outcome in (Outcome.DUPLICATE, Outcome.DEAD_LETTER)
        ),
        latency_p50_ms=percentile(latencies, 0.50),
        latency_p95_ms=percentile(latencies, 0.95),
        tokens_per_ticket=sum(s.tokens for s in scores) / len(scores) if scores else 0.0,
        stable_tickets=Proportion(successes=stable, total=len(signatures), tickets=len(signatures)),
    )


def summarise(
    pipeline: str, repeats: int, golden_fingerprint: str, scores: Iterable[CaseScore]
) -> BenchmarkSummary:
    scores = list(scores)
    seen: set[str] = set()
    errors: list[ErrorExample] = []
    for score in sorted(scores, key=lambda s: (list(Split).index(s.split), s.case_id, s.run)):
        if score.confident_error and score.case_id not in seen:
            seen.add(score.case_id)
            errors.append(
                ErrorExample(
                    case_id=score.case_id,
                    split=score.split.value,
                    subtype=score.subtype.value,
                    expected=score.expected,
                    got=score.got,
                )
            )

    return BenchmarkSummary(
        pipeline=pipeline,
        repeats=repeats,
        golden_fingerprint=golden_fingerprint,
        overall=summarise_group("all", scores),
        splits={
            split.value: summarise_group(split.value, [s for s in scores if s.split is split])
            for split in Split
            if any(s.split is split for s in scores)
        },
        adversarial_subtypes={
            subtype.value: summarise_group(
                subtype.value, [s for s in scores if s.subtype is subtype]
            )
            for subtype in Subtype
            if subtype is not Subtype.STANDARD and any(s.subtype is subtype for s in scores)
        },
        confident_errors=errors,
    )
