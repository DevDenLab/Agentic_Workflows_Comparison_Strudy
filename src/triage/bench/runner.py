"""Runs one pipeline over the golden set N times, each run on a pipeline with fresh state.

The benchmark never builds pipelines itself (import-linter forbids it): the caller passes a
factory, so v1, v1.5 and v2 are all driven through the same `TriagePipeline` contract.
"""

import hashlib
from collections.abc import Callable
from pathlib import Path

from pydantic import AwareDatetime, Field

from triage.bench.golden import GoldenSet
from triage.bench.messages import to_message
from triage.bench.scoring import CaseRun
from triage.config import ConfigModel, SemVer, load_model
from triage.contracts import TriagePipeline

PipelineFactory = Callable[[int], TriagePipeline]
"""Run number (1-based) -> a pipeline with fresh state, so dedupe never hides a repeat."""


class BenchConfig(ConfigModel):
    """config/bench.yaml"""

    version: SemVer
    received_at: AwareDatetime
    service_desk_address: str = Field(min_length=3)
    default_repeats: int = Field(ge=1)
    regression_tolerance: float = Field(ge=0, le=1)


def load_bench_config(config_dir: Path) -> BenchConfig:
    return load_model(BenchConfig, config_dir / "bench.yaml")


def run_benchmark(
    golden: GoldenSet,
    factory: PipelineFactory,
    *,
    repeats: int,
    config: BenchConfig,
    progress: Callable[[CaseRun], None] | None = None,
) -> list[CaseRun]:
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    case_runs: list[CaseRun] = []
    names: set[str] = set()
    for run in range(1, repeats + 1):
        pipeline = factory(run)
        names.add(pipeline.name)
        for case in golden.cases:
            message = to_message(
                case,
                received_at=config.received_at,
                service_desk_address=config.service_desk_address,
            )
            case_run = CaseRun(case=case, run=run, result=pipeline.triage(message))
            case_runs.append(case_run)
            if progress is not None:
                progress(case_run)
    if len(names) != 1:
        raise ValueError(f"the factory returned different pipelines across runs: {sorted(names)}")
    return case_runs


def golden_fingerprint(golden: GoldenSet) -> str:
    """Changes whenever any case or label changes, so a stale baseline is detectable."""
    digest = hashlib.sha256()
    for case in sorted(golden.cases, key=lambda c: c.id):
        digest.update(case.model_dump_json().encode("utf-8"))
    return digest.hexdigest()[:16]
