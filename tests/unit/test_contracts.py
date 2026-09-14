from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from triage.contracts import InboundMessage, TriageDecision, TriageResult, Usage


def _decision(**overrides: object) -> TriageDecision:
    data: dict[str, object] = {
        "category": "network_connectivity",
        "priority": "P3",
        "assignment_group": "network_operations",
        "draft_response": "We have received your VPN issue.",
        "confidence": 1.0,
    }
    return TriageDecision.model_validate(data | overrides)


def _result(**overrides: object) -> TriageResult:
    data: dict[str, object] = {
        "correlation_id": uuid4(),
        "message_id": "<abc@contoso.example>",
        "pipeline": "v1_conventional",
        "outcome": "auto_resolved",
        "decision": _decision(),
        "decided_by": "rules",
        "usage": Usage(latency_ms=1.5),
    }
    return TriageResult.model_validate(data | overrides)


def test_auto_resolved_result_with_decision_is_valid() -> None:
    assert _result().decision is not None


def test_auto_resolved_without_decision_is_rejected() -> None:
    with pytest.raises(ValidationError, match="auto_resolved requires a decision"):
        _result(decision=None, decided_by=None)


@pytest.mark.parametrize(
    "overrides",
    [
        {"decided_by": None},
        {"outcome": "duplicate", "decision": None},
    ],
)
def test_decision_and_decided_by_must_agree(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="both be set or both be None"):
        _result(**overrides)


def test_human_review_requires_a_reason() -> None:
    with pytest.raises(ValidationError, match="requires an escalation_reason"):
        _result(outcome="human_review", decision=None, decided_by=None)

    escalated = _result(
        outcome="human_review", decision=None, decided_by=None, escalation_reason="no rule matched"
    )
    assert escalated.escalation_reason == "no rule matched"


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_confidence_must_be_a_probability(confidence: float) -> None:
    with pytest.raises(ValidationError):
        _decision(confidence=confidence)


def test_taxonomy_ids_must_be_snake_case() -> None:
    with pytest.raises(ValidationError):
        _decision(category="Network Connectivity")


def test_unknown_fields_are_rejected_not_dropped() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _decision(severity="high")


def test_contract_models_are_immutable() -> None:
    decision = _decision()
    with pytest.raises(ValidationError):
        decision.priority = "P1"  # type: ignore[misc,assignment]


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ValidationError):
        InboundMessage(
            message_id="m-1",
            channel="email",  # type: ignore[arg-type]
            received_at=datetime(2026, 9, 14, 9, 0),  # noqa: DTZ001 - naive on purpose
            sender="nurse@contoso.example",
            subject="VPN down",
            raw_body="...",
        )


def test_result_round_trips_through_json() -> None:
    result = _result(
        audit=[
            {
                "at": datetime(2026, 9, 14, 9, 0, tzinfo=UTC),
                "component": "rule_engine",
                "event": "rule_hit",
                "detail": {"rule_id": "R010"},
            }
        ]
    )
    assert TriageResult.model_validate_json(result.model_dump_json()) == result
