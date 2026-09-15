from collections.abc import Callable
from pathlib import Path

import pytest

from triage.bench.golden import GoldenCase, GoldenSet
from triage.bench.runner import BenchConfig, golden_fingerprint, load_bench_config, run_benchmark
from triage.bench.scoring import CaseRun
from triage.contracts import InboundMessage, Priority, TriageResult

CaseFactory = Callable[..., GoldenCase]
ResultFactory = Callable[..., TriageResult]


class FakePipeline:
    def __init__(self, name: str, make_result: ResultFactory) -> None:
        self._name = name
        self._make_result = make_result
        self.seen: list[str] = []

    @property
    def name(self) -> str:
        return self._name

    def triage(self, message: InboundMessage) -> TriageResult:
        self.seen.append(message.message_id)
        return self._make_result(message_id=message.message_id)


def test_each_run_uses_a_fresh_pipeline_that_sees_every_case(
    make_case: CaseFactory, make_result: ResultFactory, bench_config: BenchConfig
) -> None:
    golden = GoldenSet((make_case("ADV-001"), make_case("ADV-002")))
    pipelines: dict[int, FakePipeline] = {}

    def factory(run: int) -> FakePipeline:
        pipelines[run] = FakePipeline("fake", make_result)
        return pipelines[run]

    case_runs = run_benchmark(golden, factory, repeats=3, config=bench_config)

    assert sorted(pipelines) == [1, 2, 3]
    assert all(len(pipeline.seen) == 2 for pipeline in pipelines.values())
    assert [(r.case.id, r.run) for r in case_runs] == [
        (case_id, run) for run in (1, 2, 3) for case_id in ("ADV-001", "ADV-002")
    ]


def test_progress_callback_sees_every_case_run(
    make_case: CaseFactory, make_result: ResultFactory, bench_config: BenchConfig
) -> None:
    seen: list[CaseRun] = []

    run_benchmark(
        GoldenSet((make_case(),)),
        lambda run: FakePipeline("fake", make_result),
        repeats=2,
        config=bench_config,
        progress=seen.append,
    )

    assert [case_run.run for case_run in seen] == [1, 2]


def test_the_pipeline_must_not_change_between_runs(
    make_case: CaseFactory, make_result: ResultFactory, bench_config: BenchConfig
) -> None:
    with pytest.raises(ValueError, match="different pipelines"):
        run_benchmark(
            GoldenSet((make_case(),)),
            lambda run: FakePipeline(f"fake-{run}", make_result),
            repeats=2,
            config=bench_config,
        )


def test_repeats_must_be_positive(
    make_case: CaseFactory, make_result: ResultFactory, bench_config: BenchConfig
) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        run_benchmark(
            GoldenSet((make_case(),)),
            lambda run: FakePipeline("fake", make_result),
            repeats=0,
            config=bench_config,
        )


def test_fingerprint_changes_only_when_the_golden_set_changes(make_case: CaseFactory) -> None:
    case = make_case()
    relabelled = case.model_copy(
        update={"label": case.label.model_copy(update={"priority": Priority.P1})}
    )

    assert golden_fingerprint(GoldenSet((case,))) == golden_fingerprint(GoldenSet((make_case(),)))
    assert golden_fingerprint(GoldenSet((case,))) != golden_fingerprint(GoldenSet((relabelled,)))


def test_shipped_bench_config_loads(config_dir: Path) -> None:
    config = load_bench_config(config_dir)

    assert config.received_at.utcoffset() is not None
    assert config.default_repeats >= 1
