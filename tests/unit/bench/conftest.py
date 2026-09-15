from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from triage.bench.golden import GoldenCase
from triage.bench.runner import BenchConfig
from triage.contracts import TriageResult, Usage

CaseFactory = Callable[..., GoldenCase]
ResultFactory = Callable[..., TriageResult]


@pytest.fixture(scope="session")
def make_case() -> CaseFactory:
    """Build a GoldenCase. Defaults: an adversarial PII email, network_connectivity / P4, auto."""

    def _make(
        case_id: str = "ADV-001",
        *,
        subtype: str = "pii",
        handling: str = "auto",
        category: str = "network_connectivity",
        priority: str = "P4",
        group: str = "network_operations",
        alternatives: tuple[dict[str, str], ...] = (),
        channel: str = "email",
        subject: str = "VPN",
        body: str = "VPN is down",
    ) -> GoldenCase:
        return GoldenCase.model_validate(
            {
                "id": case_id,
                "split": "adversarial",
                "subtype": subtype,
                "input": {
                    "channel": channel,
                    "sender": "kevin.nguyen@contoso.example",
                    "subject": subject,
                    "body": body,
                },
                "label": {
                    "category": category,
                    "impact": "low",
                    "urgency": "medium",
                    "priority": priority,
                    "assignment_group": group,
                    "handling": handling,
                    "alternatives": list(alternatives),
                },
                "rationale": "test",
            }
        )

    return _make


@pytest.fixture(scope="session")
def make_result() -> ResultFactory:
    """Build a TriageResult. Pass category=None for an escalation with no decision."""

    def _make(
        *,
        outcome: str = "auto_resolved",
        category: str | None = "network_connectivity",
        priority: str = "P4",
        group: str = "network_operations",
        message_id: str = "m-1",
        latency_ms: float = 10.0,
        tokens: int = 0,
    ) -> TriageResult:
        decision = (
            {
                "category": category,
                "priority": priority,
                "assignment_group": group,
                "draft_response": "ack",
                "confidence": 1.0,
            }
            if category is not None
            else None
        )
        return TriageResult.model_validate(
            {
                "correlation_id": uuid4(),
                "message_id": message_id,
                "pipeline": "fake",
                "outcome": outcome,
                "decision": decision,
                "decided_by": "rules" if decision else None,
                "escalation_reason": "no rule matched" if outcome == "human_review" else None,
                "usage": Usage(latency_ms=latency_ms, prompt_tokens=tokens),
            }
        )

    return _make


@pytest.fixture(scope="session")
def bench_config() -> BenchConfig:
    return BenchConfig(
        version="1.0.0",
        received_at=datetime(2026, 9, 14, 16, 0, tzinfo=UTC),
        service_desk_address="servicedesk@contoso.example",
        default_repeats=1,
        regression_tolerance=0.0,
    )
