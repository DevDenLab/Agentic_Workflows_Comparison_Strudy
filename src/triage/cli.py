import json
from collections.abc import Callable, Iterable
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from triage import __version__
from triage.bench.golden import load_golden_set
from triage.bench.report import (
    SUMMARY_MD,
    format_rate,
    load_summary,
    regressions,
    write_results,
    write_summary,
)
from triage.bench.review import write_review_sheet
from triage.bench.runner import golden_fingerprint, load_bench_config, run_benchmark
from triage.bench.scoring import score_case, summarise
from triage.config import ConfigError, Settings
from triage.container import (
    Container,
    build_container,
    build_v1,
    hybrid_benchmark_factory,
    init_cmdb,
    v1_benchmark_factory,
)
from triage.contracts import InboundMessage, TriagePipeline, TriageResult
from triage.llm.cassette import CassetteMode
from triage.v1.intake import EmailFileIntake

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Service-desk ticket triage.")

EmlPath = Annotated[
    Path, typer.Argument(exists=True, help="An .eml file, or a directory of .eml files.")
]
FullOption = Annotated[bool, typer.Option("--full", help="Print the whole TriageResult as JSON.")]


def _container() -> Container:
    try:
        return build_container()
    except ConfigError as exc:
        typer.echo(f"config invalid: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command("config-check")
def config_check() -> None:
    """Load and validate every config file. Exit 1 on the first problem."""
    container = _container()
    settings, config, v1 = container.settings, container.config, container.v1
    llm = (
        f"{settings.triage_model} @ {settings.llm_base_url}"
        if settings.llm_configured
        else "not configured (v1 needs none)"
    )
    rows = {
        "organisation": config.app.organisation,
        "timezone": config.app.timezone,
        "taxonomy": (
            f"v{config.taxonomy.version}: {len(config.taxonomy.categories)} categories, "
            f"{len(config.taxonomy.assignment_groups)} assignment groups"
        ),
        "rules": f"v{v1.rules.version}: {len(v1.rules.rules)} rules",
        "config_dir": str(settings.config_dir),
        "var_dir": str(settings.var_dir),
        "llm": llm,
    }
    for key, value in rows.items():
        typer.echo(f"{key:<14}{value}")


@app.command("cmdb-init")
def cmdb_init(
    rebuild: Annotated[bool, typer.Option(help="Drop and recreate from data/cmdb/*.sql.")] = False,
) -> None:
    """Create the local CMDB database."""
    typer.echo(f"CMDB ready at {init_cmdb(_container(), rebuild=rebuild)}")


@app.command()
def run(path: EmlPath, full: FullOption = False) -> None:
    """Triage .eml files with v1 directly, without the queue. One JSON line per ticket."""
    v1 = build_v1(_container())
    for message in _read(v1.email_intake, path):
        _print(v1.pipeline.triage(message), full)


@app.command()
def enqueue(path: EmlPath) -> None:
    """Put .eml files on the durable queue for `triage worker`."""
    v1 = build_v1(_container())
    count = 0
    for message in _read(v1.email_intake, path):
        v1.queue.enqueue(message)
        count += 1
    typer.echo(f"enqueued {count}; queue depth {v1.queue.depth()}")


@app.command()
def worker(full: FullOption = False) -> None:
    """Drain the queue: lease, triage, ack.

    If the process dies after triage but before ack, the message comes back and dedupe absorbs it.
    """
    v1 = build_v1(_container())
    while (delivery := v1.queue.lease()) is not None:
        _print(v1.pipeline.triage(delivery.message), full)
        v1.queue.ack(delivery)


@app.command("review-sheet")
def review_sheet(
    output: Annotated[Path, typer.Option(help="Where to write the CSV.")] = Path(
        "reports/label-review.csv"
    ),
) -> None:
    """Export the golden set as a CSV for label review. Opens in Excel."""
    container = _container()
    try:
        golden = load_golden_set(container.settings.data_dir / "golden")
    except ConfigError as exc:
        typer.echo(f"golden set invalid: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"wrote {write_review_sheet(golden, output)} cases to {output}")


class BenchPipeline(StrEnum):
    V1 = "v1"
    V1_5 = "v1.5"


BenchFactoryBuilder = Callable[[Settings, CassetteMode], Callable[[int], TriagePipeline]]

_BENCH_FACTORIES: dict[BenchPipeline, BenchFactoryBuilder] = {
    BenchPipeline.V1: lambda settings, _llm_mode: v1_benchmark_factory(settings),
    BenchPipeline.V1_5: lambda settings, llm_mode: hybrid_benchmark_factory(
        settings, llm_mode=llm_mode
    ),
}


@app.command()
def bench(
    pipeline: Annotated[BenchPipeline, typer.Option(help="Pipeline to benchmark.")] = (
        BenchPipeline.V1
    ),
    repeats: Annotated[
        int | None, typer.Option(min=1, help="Runs per ticket. Default: config/bench.yaml.")
    ] = None,
    out: Annotated[Path, typer.Option(help="Reports go to OUT/<pipeline name>/.")] = Path(
        "reports/benchmark"
    ),
    baseline: Annotated[
        Path | None,
        typer.Option(exists=True, dir_okay=False, help="summary.json to compare with."),
    ] = None,
    allow_draft: Annotated[
        bool, typer.Option("--allow-draft", help="Run on labels nobody has reviewed yet.")
    ] = False,
    llm_mode: Annotated[
        CassetteMode,
        typer.Option(
            help="v1.5/v2 only: 'replay' needs no key (CI); "
            "'replay_or_record' calls the provider only for tickets with no cassette yet."
        ),
    ] = "replay_or_record",
) -> None:
    """Grade a pipeline on the golden set: results, summary and charts. Exit 1 on regression."""
    from triage.bench.charts import plot_outcomes, plot_rates  # matplotlib is a dev dependency

    container = _container()
    settings = container.settings
    try:
        golden = load_golden_set(settings.data_dir / "golden")
        bench_config = load_bench_config(settings.config_dir)
    except ConfigError as exc:
        typer.echo(f"benchmark input invalid: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if not golden.reviewed and not allow_draft:
        typer.echo(
            "golden labels have not been reviewed: set reviewed_by and reviewed_on in every "
            "data/golden/*.yaml, or pass --allow-draft.",
            err=True,
        )
        raise typer.Exit(code=2)

    runs = repeats or bench_config.default_repeats
    try:
        factory = _BENCH_FACTORIES[pipeline](settings, llm_mode)
    except ConfigError as exc:
        typer.echo(f"benchmark input invalid: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    case_runs = run_benchmark(golden, factory, repeats=runs, config=bench_config)
    scored = [(case_run, score_case(case_run)) for case_run in case_runs]
    summary = summarise(
        case_runs[0].result.pipeline,
        runs,
        golden_fingerprint(golden),
        [score for _, score in scored],
    )

    target = out / summary.pipeline
    write_results(scored, target)
    write_summary(summary, target)
    plot_outcomes([summary], target / "outcomes.png")
    plot_rates([summary], target / "rates.png")
    for name, group in {**summary.splits, "all": summary.overall}.items():
        typer.echo(
            f"{name:<12} decision accuracy {format_rate(group.decision_accuracy):<16} "
            f"false-confident {format_rate(group.false_confident_rate)}"
        )
    typer.echo(f"report: {target / SUMMARY_MD}")

    if baseline is not None:
        problems = regressions(summary, load_summary(baseline), bench_config.regression_tolerance)
        for problem in problems:
            typer.echo(f"REGRESSION {problem}", err=True)
        if problems:
            raise typer.Exit(code=1)
        typer.echo(f"no regression against {baseline}")


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


def _read(intake: EmailFileIntake, path: Path) -> Iterable[InboundMessage]:
    return intake.read_directory(path) if path.is_dir() else [intake.read(path)]


def _print(result: TriageResult, full: bool) -> None:
    if full:
        typer.echo(result.model_dump_json())
        return
    decision = result.decision
    summary = {
        "message_id": result.message_id,
        "outcome": result.outcome.value,
        "category": decision.category if decision else None,
        "priority": decision.priority.value if decision else None,
        "group": decision.assignment_group if decision else None,
        "reason": result.escalation_reason,
        "latency_ms": round(result.usage.latency_ms, 2),
    }
    typer.echo(json.dumps(summary))
