"""The scoring rules from docs/labelling-guide.md §9, pinned case by case."""

from collections.abc import Callable

import pytest

from triage.bench.golden import GoldenCase
from triage.bench.scoring import (
    CaseRun,
    CaseScore,
    percentile,
    score_case,
    summarise,
    summarise_group,
    wilson_interval,
)
from triage.contracts import TriageResult

CaseFactory = Callable[..., GoldenCase]
ResultFactory = Callable[..., TriageResult]


def _score(case: GoldenCase, result: TriageResult, run: int = 1) -> CaseScore:
    return score_case(CaseRun(case=case, run=run, result=result))


# --- one case ---------------------------------------------------------------------


def test_correct_auto_resolution(make_case: CaseFactory, make_result: ResultFactory) -> None:
    score = _score(make_case(), make_result())

    assert score.correct
    assert not score.confident_error
    assert (score.category_correct, score.priority_correct, score.routing_correct) == (
        True,
        True,
        True,
    )


def test_wrong_priority_on_an_auto_resolution_is_a_confident_error(
    make_case: CaseFactory, make_result: ResultFactory
) -> None:
    score = _score(make_case(), make_result(priority="P2"))

    assert score.confident_error
    assert (score.category_correct, score.priority_correct, score.routing_correct) == (
        True,
        False,
        True,
    )


def test_escalating_an_auto_case_earns_no_credit_but_is_not_an_error(
    make_case: CaseFactory, make_result: ResultFactory
) -> None:
    score = _score(make_case(), make_result(outcome="human_review", category=None))

    assert score.escalated
    assert not score.correct
    assert not score.confident_error
    assert score.category_correct is False


def test_escalating_a_must_escalate_case_is_correct(
    make_case: CaseFactory, make_result: ResultFactory
) -> None:
    case = make_case(subtype="must_escalate", handling="escalate")

    score = _score(case, make_result(outcome="human_review", category=None))

    assert score.correct
    assert score.category_correct is None


def test_auto_resolving_a_must_escalate_case_is_a_confident_error_even_with_right_labels(
    make_case: CaseFactory, make_result: ResultFactory
) -> None:
    case = make_case(subtype="must_escalate", handling="escalate")

    score = _score(case, make_result())

    assert score.confident_error
    assert score.expected.startswith("escalate (")


@pytest.mark.parametrize(("priority", "correct"), [("P3", True), ("P2", False)])
def test_an_alternative_reading_is_judged_on_its_own_priority(
    make_case: CaseFactory, make_result: ResultFactory, priority: str, correct: bool
) -> None:
    case = make_case(
        subtype="ambiguous",
        category="clinical_devices",
        priority="P2",
        group="clinical_engineering",
        alternatives=(
            {
                "category": "network_connectivity",
                "assignment_group": "network_operations",
                "priority": "P3",
            },
        ),
    )
    result = make_result(
        category="network_connectivity", priority=priority, group="network_operations"
    )

    assert _score(case, result).correct is correct


def test_dead_letter_is_neither_an_auto_resolution_nor_an_escalation(
    make_case: CaseFactory, make_result: ResultFactory
) -> None:
    score = _score(make_case(), make_result(outcome="dead_letter"))

    assert not score.auto_resolved
    assert not score.escalated
    assert not score.confident_error


# --- statistics -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("p", "n", "low", "high"),
    [(0.5, 10, 0.2366, 0.7634), (1.0, 50, 0.9287, 1.0), (0.0, 50, 0.0, 0.0713)],
)
def test_wilson_interval_matches_reference_values(
    p: float, n: int, low: float, high: float
) -> None:
    assert wilson_interval(p, n) == pytest.approx((low, high), abs=1e-4)


def test_wilson_interval_needs_samples() -> None:
    with pytest.raises(ValueError, match="positive"):
        wilson_interval(0.5, 0)


def test_percentile_interpolates() -> None:
    assert percentile([10.0, 20.0, 30.0, 40.0], 0.5) == 25.0
    assert percentile([float(v) for v in range(1, 101)], 0.95) == pytest.approx(95.05)
    assert percentile([5.0], 0.95) == 5.0
    assert percentile([], 0.5) is None


# --- aggregation ------------------------------------------------------------------


def test_summary_uses_the_agreed_denominators(
    make_case: CaseFactory, make_result: ResultFactory
) -> None:
    scores = [
        _score(make_case("ADV-001"), make_result()),
        _score(make_case("ADV-002"), make_result(priority="P1")),
        _score(make_case("ADV-003"), make_result(outcome="human_review", category=None)),
        _score(
            make_case("ADV-004", subtype="must_escalate", handling="escalate"),
            make_result(outcome="human_review", category=None),
        ),
        _score(make_case("ADV-005"), make_result(outcome="dead_letter")),
    ]

    group = summarise_group("test", scores)

    def counts(name: str) -> tuple[int, int]:
        proportion = getattr(group, name)
        return proportion.successes, proportion.total

    assert counts("decision_accuracy") == (2, 5)  # 001 right, 004 rightly escalated
    assert counts("category_accuracy") == (2, 4)  # over the four auto-handling cases
    assert counts("auto_resolution_rate") == (2, 5)
    assert counts("escalation_rate") == (2, 5)
    assert counts("accuracy_when_auto_resolved") == (1, 2)
    assert counts("false_confident_rate") == (1, 2)
    assert counts("escalation_recall") == (1, 1)
    assert group.unexpected_outcomes == 1


def test_interval_sample_size_is_tickets_not_runs(
    make_case: CaseFactory, make_result: ResultFactory
) -> None:
    case = make_case()
    scores = [_score(case, make_result(), run) for run in (1, 2, 3)]

    accuracy = summarise_group("test", scores).decision_accuracy

    assert (accuracy.successes, accuracy.total, accuracy.tickets) == (3, 3, 1)


def test_a_ticket_that_changes_between_runs_is_unstable(
    make_case: CaseFactory, make_result: ResultFactory
) -> None:
    case = make_case()
    scores = [_score(case, make_result(), 1), _score(case, make_result(priority="P3"), 2)]

    stable = summarise_group("test", scores).stable_tickets

    assert (stable.successes, stable.total) == (0, 1)


def test_latency_and_tokens_are_aggregated(
    make_case: CaseFactory, make_result: ResultFactory
) -> None:
    scores = [
        _score(make_case(f"ADV-00{i}"), make_result(latency_ms=10.0 * i, tokens=100 * i))
        for i in range(1, 5)
    ]

    group = summarise_group("test", scores)

    assert group.latency_p50_ms == 25.0
    assert group.tokens_per_ticket == 250.0


def test_confident_errors_are_listed_once_per_ticket(
    make_case: CaseFactory, make_result: ResultFactory
) -> None:
    case = make_case()
    scores = [_score(case, make_result(priority="P1"), run) for run in (1, 2)]

    summary = summarise("fake", 2, "fingerprint", scores)

    (error,) = summary.confident_errors
    assert error.case_id == "ADV-001"
    assert error.got == "auto_resolved: network_connectivity / P1 / network_operations"
    assert error.expected == "network_connectivity / P4 / network_operations"
