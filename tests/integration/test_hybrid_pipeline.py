"""v1.5 end to end: real config, real SQLite, a scripted (non-network) LLM transport.

Rule-hit tickets prove nothing changed from v1. Rule-miss tickets prove the LLM path: classify,
finish through the same v1 components, or fall back to human review when the model can't help.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from triage.clock import FixedClock
from triage.config import Settings
from triage.container import Container, HybridRuntime, build_container, build_hybrid
from triage.contracts import Channel, DecidedBy, InboundMessage, Outcome, Priority, TriagePipeline
from triage.llm.client import LlmClient

NOW = datetime(2026, 9, 14, 15, 0, tzinfo=UTC)


class ScriptedTransport:
    """Returns one canned /chat/completions response per call, in order. Never touches a network."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.payloads: list[dict[str, Any]] = []

    def send(self, payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
        self.payloads.append(payload)
        if not self._responses:
            raise AssertionError("ScriptedTransport ran out of responses")
        return self._responses.pop(0)


def tool_call_response(**arguments: object) -> dict[str, Any]:
    return {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {
                                "name": "classify_ticket",
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ]
                },
            }
        ],
        "usage": {"prompt_tokens": 150, "completion_tokens": 12},
    }


def no_tool_call_response() -> dict[str, Any]:
    return {
        "choices": [{"finish_reason": "stop", "message": {"content": "sorry, I can't help"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 5},
    }


def _container(config_dir: Path, data_dir: Path, var_dir: Path) -> Container:
    settings = Settings(
        _env_file=None,
        config_dir=config_dir,
        data_dir=data_dir,
        var_dir=var_dir,
        log_level="WARNING",
    )
    return build_container(settings, clock=FixedClock(NOW))


def _hybrid(
    container: Container, responses: list[dict[str, Any]]
) -> tuple[HybridRuntime, ScriptedTransport]:
    transport = ScriptedTransport(responses)
    client = LlmClient(transport, "deepseek-flash", container.clock)
    return build_hybrid(container, client, sleep=lambda _: None), transport


@pytest.fixture
def container(config_dir: Path, data_dir: Path, tmp_path: Path) -> Container:
    return _container(config_dir, data_dir, tmp_path / "var")


def _web_form(body: str, message_id: str = "webform:F-1") -> InboundMessage:
    return InboundMessage(
        message_id=message_id,
        channel=Channel.WEB_FORM,
        received_at=NOW,
        sender="liam.chen@contoso.example",
        subject="Help",
        raw_body=body,
    )


def test_pipeline_satisfies_the_shared_contract(container: Container) -> None:
    hybrid, _ = _hybrid(container, [])
    assert isinstance(hybrid.pipeline, TriagePipeline)


def test_rule_hit_never_calls_the_model(container: Container, data_dir: Path) -> None:
    hybrid, transport = _hybrid(container, [])

    result = hybrid.pipeline.triage(
        hybrid.email_intake.read(data_dir / "samples" / "01_vpn_drops.eml")
    )

    assert result.outcome is Outcome.AUTO_RESOLVED
    assert result.decided_by is DecidedBy.RULES
    assert transport.payloads == []
    assert result.usage.llm_calls == 0


def test_rule_miss_is_classified_by_the_model_and_finished_like_v1(container: Container) -> None:
    hybrid, transport = _hybrid(
        container,
        [tool_call_response(category="network_connectivity", urgency="medium", confidence=0.87)],
    )

    result = hybrid.pipeline.triage(
        InboundMessage(
            message_id="webform:F-1",
            channel=Channel.WEB_FORM,
            received_at=NOW,
            sender="kevin.nguyen@contoso.example",  # Finance: non-clinical, so impact stays "low"
            subject="Help",
            raw_body="None of the work sites load when I connect from home.",
        )
    )

    assert result.outcome is Outcome.AUTO_RESOLVED
    assert result.decided_by is DecidedBy.LLM_NODE
    decision = result.decision
    assert decision is not None
    assert decision.category == "network_connectivity"
    assert decision.priority is Priority.P4
    assert decision.assignment_group == "network_operations"
    assert decision.confidence == 0.87
    assert decision.citations[0].source_id == "llm:classify_ticket"
    assert result.usage.llm_calls == 1
    assert result.usage.prompt_tokens == 150
    assert len(transport.payloads) == 1
    assert hybrid.itsm.count() == 1


def test_repeated_bad_output_falls_back_to_human_review(container: Container) -> None:
    hybrid, transport = _hybrid(
        container, [no_tool_call_response(), no_tool_call_response(), no_tool_call_response()]
    )

    result = hybrid.pipeline.triage(_web_form("The thing on the wall is beeping strangely."))

    assert result.outcome is Outcome.HUMAN_REVIEW
    assert result.escalation_reason is not None
    assert "llm classification failed" in result.escalation_reason
    assert len(transport.payloads) == 3  # max_repair_attempts=2 -> 3 total tries
    assert hybrid.itsm.count() == 0


def test_priority_matrix_and_cmdb_signals_still_apply_on_the_llm_path(
    container: Container,
) -> None:
    """Same downstream components as v1: a clinical sender should still raise impact."""
    hybrid, _ = _hybrid(
        container,
        [tool_call_response(category="network_connectivity", urgency="high", confidence=0.9)],
    )

    result = hybrid.pipeline.triage(
        InboundMessage(
            message_id="m-icu",
            channel=Channel.EMAIL,
            received_at=NOW,
            sender="priya.raman@contoso.example",  # ICU, a clinical department in the CMDB seed
            subject="Connectivity",
            # Deliberately avoids every rule keyword (wifi/wireless/vpn/ethernet/...) and every
            # widespread-impact phrase ("everyone", "whole unit", ...), so impact comes only from
            # the sender's clinical department (I2), not a rule hit or a widespread signal (I1).
            raw_body="Connectivity on this unit keeps dropping partway through my shift.",
        )
    )

    assert result.decision is not None
    assert result.decision.priority is Priority.P2  # medium impact (clinical dept) x high urgency


def test_audit_trail_names_the_llm_step(container: Container) -> None:
    hybrid, _ = _hybrid(
        container, [tool_call_response(category="printing", urgency="low", confidence=0.6)]
    )

    # "copier" isn't a rule keyword (rules use "printer"), so this is a genuine rule miss.
    result = hybrid.pipeline.triage(_web_form("The copier on 2 needs a new ink cartridge."))

    components = [event.component for event in result.audit]
    assert "llm_classifier" in components
    assert (
        components.index("rule_engine")
        < components.index("llm_classifier")
        < components.index("priority_matrix")
    )
