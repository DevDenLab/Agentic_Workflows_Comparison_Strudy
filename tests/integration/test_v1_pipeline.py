"""v1 end to end: real config, real SQLite files in a temp directory, fixed clock, no network.

Still deterministic tests with exact asserts: nothing in v1 varies between runs.
"""

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from triage.cli import app
from triage.clock import FixedClock
from triage.config import Settings
from triage.container import Container, V1Runtime, build_container, build_v1
from triage.contracts import Channel, DecidedBy, InboundMessage, Outcome, Priority, TriagePipeline
from triage.v1.itsm import FaultInjectionConfig

NOW = datetime(2026, 9, 14, 15, 0, tzinfo=UTC)
V1_STEPS = [
    "parser",
    "extractor",
    "cmdb",
    "rule_engine",
    "priority_matrix",
    "sla",
    "routing_table",
    "responder",
    "itsm",
]


def _container(config_dir: Path, data_dir: Path, var_dir: Path) -> Container:
    settings = Settings(
        _env_file=None,
        config_dir=config_dir,
        data_dir=data_dir,
        var_dir=var_dir,
        log_level="WARNING",
    )
    return build_container(settings, clock=FixedClock(NOW))


@pytest.fixture
def container(config_dir: Path, data_dir: Path, tmp_path: Path) -> Container:
    return _container(config_dir, data_dir, tmp_path / "var")


@pytest.fixture
def v1(container: Container) -> V1Runtime:
    return build_v1(container, sleep=lambda _: None)


@pytest.fixture
def samples(data_dir: Path) -> Path:
    return data_dir / "samples"


def _web_form(description: str, message_id: str = "webform:F-1") -> InboundMessage:
    return InboundMessage(
        message_id=message_id,
        channel=Channel.WEB_FORM,
        received_at=NOW,
        sender="liam.chen@contoso.example",
        subject="Help",
        raw_body=description,
    )


def test_pipeline_satisfies_the_shared_contract(v1: V1Runtime) -> None:
    assert isinstance(v1.pipeline, TriagePipeline)


def test_rule_hit_is_triaged_end_to_end(v1: V1Runtime, samples: Path) -> None:
    result = v1.pipeline.triage(v1.email_intake.read(samples / "01_vpn_drops.eml"))

    assert result.outcome is Outcome.AUTO_RESOLVED
    assert result.decided_by is DecidedBy.RULES
    decision = result.decision
    assert decision is not None
    assert (decision.category, decision.priority, decision.assignment_group) == (
        "network_connectivity",
        Priority.P4,
        "network_operations",
    )
    assert decision.enrichment.asset_tag == "CH-LT-00042"
    assert decision.citations[0].source_id == "rule:R040"
    assert decision.draft_response.startswith("Hello Kevin,")
    assert "Thanks" not in decision.draft_response
    assert [event.component for event in result.audit] == V1_STEPS
    assert v1.itsm.count() == 1


def test_whole_unit_clinical_outage_is_p1_for_clinical_engineering(
    v1: V1Runtime, samples: Path
) -> None:
    result = v1.pipeline.triage(v1.email_intake.read(samples / "02_scanners_unit_down.eml"))

    assert result.decision is not None
    assert result.decision.priority is Priority.P1
    assert result.decision.assignment_group == "clinical_engineering"
    (assessed,) = [e for e in result.audit if e.event == "assessed"]
    assert assessed.detail["reasons"] == ["ticket says 'whole unit'"]


def test_html_email_is_parsed_and_mfa_override_routes_it(v1: V1Runtime, samples: Path) -> None:
    result = v1.pipeline.triage(v1.email_intake.read(samples / "04_html_mfa.eml"))

    assert result.decision is not None
    assert result.decision.category == "access_identity"
    assert result.decision.assignment_group == "identity_access"


def test_new_phrasing_goes_to_the_human_queue(v1: V1Runtime, samples: Path) -> None:
    result = v1.pipeline.triage(v1.email_intake.read(samples / "05_novel_phrasing.eml"))

    assert result.outcome is Outcome.HUMAN_REVIEW
    assert result.escalation_reason == "no rule matched"
    assert result.decision is None
    (queued,) = v1.human_queue.items()
    assert queued.ticket is not None
    assert queued.draft is None
    assert v1.itsm.count() == 0


def test_duplicate_message_is_not_processed_twice(v1: V1Runtime, samples: Path) -> None:
    message = v1.email_intake.read(samples / "01_vpn_drops.eml")

    v1.pipeline.triage(message)
    again = v1.pipeline.triage(message)

    assert again.outcome is Outcome.DUPLICATE
    assert [event.component for event in again.audit] == ["queue"]
    assert v1.itsm.count() == 1


def test_empty_ticket_fails_validation_and_goes_to_a_human(v1: V1Runtime) -> None:
    result = v1.pipeline.triage(_web_form("   \n  "))

    assert result.outcome is Outcome.HUMAN_REVIEW
    assert result.escalation_reason is not None
    assert result.escalation_reason.startswith("invalid ticket: text")
    (queued,) = v1.human_queue.items()
    assert queued.ticket is None


def test_itsm_outage_ends_in_the_dead_letter_queue(container: Container) -> None:
    runtime = container.v1.runtime
    always_down = runtime.itsm.model_copy(
        update={"fault_injection": FaultInjectionConfig(failure_rate=1.0, seed=1)}
    )
    broken = replace(
        container,
        v1=replace(container.v1, runtime=runtime.model_copy(update={"itsm": always_down})),
    )
    sleeps: list[float] = []
    v1 = build_v1(broken, sleep=sleeps.append)

    result = v1.pipeline.triage(_web_form("VPN is down"))

    assert result.outcome is Outcome.DEAD_LETTER
    assert result.decision is not None
    assert v1.dead_letters.depth() == 1
    assert len(sleeps) == runtime.itsm.retry.max_attempts - 1


def test_same_input_gives_the_same_decision(
    config_dir: Path, data_dir: Path, samples: Path, tmp_path: Path
) -> None:
    decisions = []
    for run in ("a", "b"):
        v1 = build_v1(_container(config_dir, data_dir, tmp_path / run), sleep=lambda _: None)
        decisions.append(
            v1.pipeline.triage(v1.email_intake.read(samples / "02_scanners_unit_down.eml")).decision
        )

    assert decisions[0] is not None
    assert decisions[0] == decisions[1]


def test_metrics_reflect_the_run(container: Container, v1: V1Runtime, samples: Path) -> None:
    for message in v1.email_intake.read_directory(samples):
        v1.pipeline.triage(message)

    registry = container.metrics.registry

    def tickets(outcome: str, decided_by: str) -> float | None:
        labels = {"pipeline": "v1_conventional", "outcome": outcome, "decided_by": decided_by}
        return registry.get_sample_value("triage_tickets_total", labels)

    assert tickets("auto_resolved", "rules") == 4
    assert tickets("human_review", "none") == 1
    assert registry.get_sample_value("triage_rule_misses_total") == 1
    assert registry.get_sample_value("triage_human_queue_depth") == 1


def test_cli_queue_and_worker_process_every_sample(
    config_dir: Path, data_dir: Path, samples: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("VAR_DIR", str(tmp_path / "var"))
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    runner = CliRunner()

    enqueued = runner.invoke(app, ["enqueue", str(samples)])
    drained = runner.invoke(app, ["worker"])

    assert enqueued.exit_code == 0, enqueued.output
    assert "enqueued 5" in enqueued.output
    assert drained.exit_code == 0, drained.output
    outcomes = [json.loads(line)["outcome"] for line in drained.output.splitlines()]
    assert sorted(outcomes) == ["auto_resolved"] * 4 + ["human_review"]
