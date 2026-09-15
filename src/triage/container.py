"""Composition root. The only module that constructs and wires objects (enforced by import-linter).

Components receive their dependencies as constructor arguments; none of them reach for globals.
"""

import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from triage.clock import Clock, SystemClock
from triage.config import ConfigError, LoadedConfig, Settings, load_config, load_model
from triage.contracts import TriagePipeline
from triage.hybrid.classifier import LlmClassifier, LlmConfig
from triage.hybrid.pipeline import HybridComponents, HybridPipeline
from triage.llm.cassette import CassetteMode, CassetteTransport
from triage.llm.client import HttpxTransport, LlmClient
from triage.observability.logging import configure_logging
from triage.observability.metrics import TriageMetrics
from triage.v1.cmdb import SqliteCmdb, create_cmdb
from triage.v1.extractor import Extractor
from triage.v1.human_queue import SqliteHumanQueue
from triage.v1.intake import EmailFileIntake, WebFormIntake
from triage.v1.itsm import FaultInjector, ItsmWriter, SqliteDeadLetterQueue, SqliteItsm
from triage.v1.parser import Parser
from triage.v1.pipeline import ConventionalComponents, ConventionalPipeline
from triage.v1.priority_matrix import PriorityMatrix
from triage.v1.queue import SqliteIdempotencyStore, SqliteMessageQueue
from triage.v1.responder import Responder
from triage.v1.routing_table import RoutingTable
from triage.v1.rule_engine import RuleEngine
from triage.v1.settings import V1Config, load_v1_config
from triage.v1.sla import SlaCalculator
from triage.v1.storage import SqliteDatabase


def load_llm_config(config_dir: Path) -> LlmConfig:
    return load_model(LlmConfig, config_dir / "llm.yaml")


@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    config: LoadedConfig
    v1: V1Config
    clock: Clock
    metrics: TriageMetrics


def build_container(settings: Settings | None = None, clock: Clock | None = None) -> Container:
    settings = settings or Settings()
    configure_logging(settings.log_level, settings.log_format)
    config = load_config(settings.config_dir)
    return Container(
        settings=settings,
        config=config,
        v1=load_v1_config(settings.config_dir, config.taxonomy),
        clock=clock or SystemClock(),
        metrics=TriageMetrics(),
    )


def init_cmdb(container: Container, *, rebuild: bool = False) -> Path:
    """Create the CMDB from data/cmdb/*.sql if it doesn't exist yet (or always, with rebuild)."""
    path = container.settings.var_dir / "cmdb.sqlite3"
    if rebuild or not path.is_file():
        sql = container.settings.data_dir / "cmdb"
        create_cmdb(path, sql / "schema.sql", sql / "seed.sql")
    return path


@dataclass(frozen=True, slots=True)
class V1Runtime:
    pipeline: ConventionalPipeline
    queue: SqliteMessageQueue
    email_intake: EmailFileIntake
    web_form_intake: WebFormIntake
    itsm: SqliteItsm
    human_queue: SqliteHumanQueue
    dead_letters: SqliteDeadLetterQueue


def build_v1(container: Container, *, sleep: Callable[[float], None] = time.sleep) -> V1Runtime:
    settings, config, v1, clock = (
        container.settings,
        container.config,
        container.v1,
        container.clock,
    )
    runtime = v1.runtime

    triage_db = SqliteDatabase(settings.var_dir / "triage.sqlite3", runtime.storage)
    itsm = SqliteItsm(
        SqliteDatabase(settings.var_dir / "itsm.sqlite3", runtime.storage),
        clock,
        FaultInjector(runtime.itsm.fault_injection),
    )
    dead_letters = SqliteDeadLetterQueue(triage_db, clock)
    human_queue = SqliteHumanQueue(triage_db, clock)

    components = ConventionalComponents(
        idempotency=SqliteIdempotencyStore(triage_db, clock),
        parser=Parser(v1.parsing.parser),
        extractor=Extractor(v1.parsing.extractor),
        cmdb=SqliteCmdb(init_cmdb(container)),
        rule_engine=RuleEngine(v1.rules),
        priority_matrix=PriorityMatrix(v1.priority),
        sla=SlaCalculator(v1.sla, config.app.timezone),
        routing=RoutingTable(v1.routing),
        responder=Responder(v1.templates_dir, config.taxonomy, config.app.timezone),
        itsm_writer=ItsmWriter(itsm, dead_letters, runtime.itsm.retry, sleep=sleep),
        dead_letters=dead_letters,
        human_queue=human_queue,
    )
    return V1Runtime(
        pipeline=ConventionalPipeline(components, clock, container.metrics),
        queue=SqliteMessageQueue(triage_db, clock, runtime.queue),
        email_intake=EmailFileIntake(clock),
        web_form_intake=WebFormIntake(clock),
        itsm=itsm,
        human_queue=human_queue,
        dead_letters=dead_letters,
    )


def v1_benchmark_factory(settings: Settings) -> Callable[[int], TriagePipeline]:
    """Pipelines for `triage bench`. Each run gets its own empty state directory, so the
    idempotency store never dedupes a repeated ticket and every run starts with an empty ITSM."""

    def factory(run: int) -> TriagePipeline:
        run_dir = settings.var_dir / "bench" / "v1" / f"run-{run}"
        shutil.rmtree(run_dir, ignore_errors=True)
        run_settings = settings.model_copy(update={"var_dir": run_dir, "log_level": "WARNING"})
        return build_v1(build_container(run_settings)).pipeline

    return factory


def build_llm_client(settings: Settings, clock: Clock, *, mode: CassetteMode) -> LlmClient:
    """`mode` controls the cassette policy (record/replay/replay_or_record); see llm/cassette.py.

    Raises ConfigError if LLM_BASE_URL / LLM_API_KEY / TRIAGE_MODEL are not set — v1.5 and v2 need
    them, v1 does not.
    """
    base_url, api_key, model = settings.llm_base_url, settings.llm_api_key, settings.triage_model
    if base_url is None or api_key is None or model is None:
        raise ConfigError(
            "LLM not configured: set LLM_BASE_URL, LLM_API_KEY and TRIAGE_MODEL (see .env.example)"
        )
    transport = CassetteTransport(
        HttpxTransport(base_url, api_key.get_secret_value()),
        settings.cassette_dir / "v1_5_hybrid",
        mode,
    )
    return LlmClient(transport, model, clock)


@dataclass(frozen=True, slots=True)
class HybridRuntime:
    pipeline: HybridPipeline
    queue: SqliteMessageQueue
    email_intake: EmailFileIntake
    web_form_intake: WebFormIntake
    itsm: SqliteItsm
    human_queue: SqliteHumanQueue
    dead_letters: SqliteDeadLetterQueue


def build_hybrid(
    container: Container, llm_client: LlmClient, *, sleep: Callable[[float], None] = time.sleep
) -> HybridRuntime:
    """Same components as build_v1, plus the LLM classifier at the rule-miss node."""
    settings, config, v1 = container.settings, container.config, container.v1
    clock = container.clock
    runtime = v1.runtime

    triage_db = SqliteDatabase(settings.var_dir / "triage.sqlite3", runtime.storage)
    itsm = SqliteItsm(
        SqliteDatabase(settings.var_dir / "itsm.sqlite3", runtime.storage),
        clock,
        FaultInjector(runtime.itsm.fault_injection),
    )
    dead_letters = SqliteDeadLetterQueue(triage_db, clock)
    human_queue = SqliteHumanQueue(triage_db, clock)
    llm_config = load_llm_config(settings.config_dir)
    classifier = LlmClassifier(
        llm_client,
        llm_config,
        config.taxonomy,
        settings.config_dir / "prompts",
        config.app.organisation,
    )

    components = HybridComponents(
        idempotency=SqliteIdempotencyStore(triage_db, clock),
        parser=Parser(v1.parsing.parser),
        extractor=Extractor(v1.parsing.extractor),
        cmdb=SqliteCmdb(init_cmdb(container)),
        rule_engine=RuleEngine(v1.rules),
        classifier=classifier,
        priority_matrix=PriorityMatrix(v1.priority),
        sla=SlaCalculator(v1.sla, config.app.timezone),
        routing=RoutingTable(v1.routing),
        responder=Responder(v1.templates_dir, config.taxonomy, config.app.timezone),
        itsm_writer=ItsmWriter(itsm, dead_letters, runtime.itsm.retry, sleep=sleep),
        dead_letters=dead_letters,
        human_queue=human_queue,
    )
    return HybridRuntime(
        pipeline=HybridPipeline(components, clock, container.metrics),
        queue=SqliteMessageQueue(triage_db, clock, runtime.queue),
        email_intake=EmailFileIntake(clock),
        web_form_intake=WebFormIntake(clock),
        itsm=itsm,
        human_queue=human_queue,
        dead_letters=dead_letters,
    )


def hybrid_benchmark_factory(
    settings: Settings, *, llm_mode: CassetteMode
) -> Callable[[int], TriagePipeline]:
    """Pipelines for `triage bench --pipeline v1.5`. Each run gets fresh v1-side state (dedupe,
    ITSM), but the cassette directory is stable across runs, so only the first run per unique
    ticket ever calls the provider — replays are free.
    """
    clock = SystemClock()
    llm_client = build_llm_client(settings, clock, mode=llm_mode)

    def factory(run: int) -> TriagePipeline:
        run_dir = settings.var_dir / "bench" / "v1_5_hybrid" / f"run-{run}"
        shutil.rmtree(run_dir, ignore_errors=True)
        run_settings = settings.model_copy(update={"var_dir": run_dir, "log_level": "WARNING"})
        return build_hybrid(build_container(run_settings, clock=clock), llm_client).pipeline

    return factory
