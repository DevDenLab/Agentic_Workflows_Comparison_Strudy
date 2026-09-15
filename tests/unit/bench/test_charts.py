from collections.abc import Callable
from pathlib import Path

import pytest

from triage.bench.charts import (
    INK_PRIMARY,
    WHITE,
    ink_on,
    outcome_shares,
    plot_outcomes,
    plot_rates,
)
from triage.bench.golden import GoldenCase
from triage.bench.scoring import BenchmarkSummary, CaseRun, score_case, summarise
from triage.contracts import TriageResult

CaseFactory = Callable[..., GoldenCase]
ResultFactory = Callable[..., TriageResult]
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def summary(make_case: CaseFactory, make_result: ResultFactory) -> BenchmarkSummary:
    case_runs = [
        CaseRun(make_case("ADV-001"), 1, make_result()),
        CaseRun(make_case("ADV-002"), 1, make_result(priority="P1")),
        CaseRun(make_case("ADV-003"), 1, make_result(outcome="human_review", category=None)),
        CaseRun(
            make_case("ADV-004", subtype="must_escalate", handling="escalate"),
            1,
            make_result(outcome="human_review", category=None),
        ),
        CaseRun(make_case("ADV-005"), 1, make_result(outcome="dead_letter")),
    ]
    return summarise("fake", 1, "fingerprint", [score_case(case_run) for case_run in case_runs])


def test_outcome_shares_partition_every_ticket_run(summary: BenchmarkSummary) -> None:
    shares = outcome_shares(summary.overall)

    assert {share.label: share.count for share in shares} == {
        "Correct": 2,
        "Escalated, no credit": 1,
        "Confident error": 1,
        "Infrastructure failure": 1,
    }
    assert sum(share.share for share in shares) == pytest.approx(1.0)


@pytest.mark.parametrize("pipelines", [1, 3])
def test_charts_render_to_png(summary: BenchmarkSummary, tmp_path: Path, pipelines: int) -> None:
    summaries = [summary.model_copy(update={"pipeline": f"p{i}"}) for i in range(pipelines)]

    for plot, name in ((plot_outcomes, "outcomes.png"), (plot_rates, "rates.png")):
        path = plot(summaries, tmp_path / name)
        assert path.read_bytes()[:8] == PNG_SIGNATURE


def test_more_than_three_pipelines_are_refused(summary: BenchmarkSummary, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at most 3 pipelines"):
        plot_rates([summary] * 4, tmp_path / "rates.png")


def test_in_bar_label_ink_is_chosen_for_contrast() -> None:
    assert ink_on("#fcfcfb") == INK_PRIMARY
    assert ink_on("#0d366b") == WHITE
