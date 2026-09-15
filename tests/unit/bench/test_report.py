import json
from collections.abc import Callable
from pathlib import Path

import pytest

from triage.bench.golden import GoldenCase
from triage.bench.report import (
    SUMMARY_JSON,
    SUMMARY_MD,
    format_rate,
    load_summary,
    regressions,
    render_markdown,
    write_results,
    write_summary,
)
from triage.bench.scoring import (
    BenchmarkSummary,
    CaseRun,
    CaseScore,
    Proportion,
    score_case,
    summarise,
)
from triage.contracts import TriageResult

CaseFactory = Callable[..., GoldenCase]
ResultFactory = Callable[..., TriageResult]
Scored = list[tuple[CaseRun, CaseScore]]


@pytest.fixture
def scored(make_case: CaseFactory, make_result: ResultFactory) -> Scored:
    case_runs = [
        CaseRun(case=make_case("ADV-001"), run=1, result=make_result()),
        CaseRun(case=make_case("ADV-002"), run=1, result=make_result(priority="P1")),
        CaseRun(
            case=make_case("ADV-003", subtype="must_escalate", handling="escalate"),
            run=1,
            result=make_result(outcome="human_review", category=None),
        ),
    ]
    return [(case_run, score_case(case_run)) for case_run in case_runs]


def _summary(scored: Scored, fingerprint: str = "abc") -> BenchmarkSummary:
    return summarise("fake", 1, fingerprint, [score for _, score in scored])


def test_results_file_has_one_json_line_per_case_run(scored: Scored, tmp_path: Path) -> None:
    path = write_results(scored, tmp_path)

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    assert [record["case_id"] for record in records] == ["ADV-001", "ADV-002", "ADV-003"]
    assert records[1]["confident_error"] is True
    assert records[2]["expected"].startswith("escalate")


def test_summary_json_round_trips(scored: Scored, tmp_path: Path) -> None:
    summary = _summary(scored)

    write_summary(summary, tmp_path)

    assert load_summary(tmp_path / SUMMARY_JSON) == summary
    assert (tmp_path / SUMMARY_MD).is_file()


def test_markdown_shows_rates_with_intervals_and_lists_confident_errors(scored: Scored) -> None:
    text = render_markdown(_summary(scored))

    assert "| Metric | adversarial | all |" in text
    assert "| Decision accuracy | 66.7% (21–94) |" in text
    assert "| Stable across runs | — (1 run) |" in text
    assert "## Adversarial subtypes" in text
    assert "## Confident errors (1 ticket)" in text
    assert "| ADV-002 | pii |" in text


def test_rate_without_data_is_a_dash() -> None:
    assert format_rate(Proportion(successes=0, total=0, tickets=0)) == "—"


def test_a_summary_does_not_regress_against_itself(scored: Scored) -> None:
    summary = _summary(scored)

    assert regressions(summary, summary, tolerance=0.0) == []


def test_changes_beyond_tolerance_are_regressions(
    scored: Scored, make_result: ResultFactory
) -> None:
    baseline = _summary(scored)
    worse = [
        (case_run, score_case(CaseRun(case_run.case, 1, make_result(priority="P1"))))
        for case_run, _ in scored
    ]
    current = _summary(worse)

    problems = regressions(current, baseline, tolerance=0.0)

    assert "all: decision_accuracy moved from 66.7% to 0.0%" in problems
    assert any("false_confident_rate" in problem for problem in problems)
    assert any("escalation_recall" in problem for problem in problems)
    assert regressions(current, baseline, tolerance=1.0) == []


def test_a_changed_golden_set_invalidates_the_baseline(scored: Scored) -> None:
    (problem,) = regressions(_summary(scored, "new"), _summary(scored, "old"), tolerance=0.0)

    assert "golden set changed" in problem


def test_a_baseline_for_another_pipeline_is_rejected(scored: Scored) -> None:
    other = _summary(scored).model_copy(update={"pipeline": "other"})

    with pytest.raises(ValueError, match="baseline is for other"):
        regressions(_summary(scored), other, tolerance=0.0)
