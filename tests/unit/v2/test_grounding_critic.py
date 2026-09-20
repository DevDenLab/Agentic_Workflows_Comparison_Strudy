"""GroundingCritic.review: the LLM half of the critic (9b), exercised with a scripted transport."""

import json
from typing import Any

import pytest

from triage.v2.critic import CriticConfig, CriticError, GroundingCritic

from .conftest import make_client

CONFIG = CriticConfig(temperature=0.0, max_output_tokens=100, timeout_seconds=10)


def _verdict_response(grounded: bool, reason: str) -> dict[str, Any]:
    return {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "tool_calls": [
                        {
                            "id": "1",
                            "function": {
                                "name": "critic_verdict",
                                "arguments": json.dumps({"grounded": grounded, "reason": reason}),
                            },
                        }
                    ]
                },
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


def test_grounded_verdict_is_parsed() -> None:
    client, transport = make_client([_verdict_response(True, "supported by the excerpt")])

    verdict = GroundingCritic(client, CONFIG).review(
        category="printing", urgency="low", rationale="toner low", cited_excerpts=["toner runbook"]
    )

    assert verdict.grounded
    assert verdict.reason == "supported by the excerpt"
    payload = transport.payloads[0]
    assert payload["tool_choice"] == {"type": "function", "function": {"name": "critic_verdict"}}
    assert "toner runbook" in payload["messages"][1]["content"]


def test_ungrounded_verdict_is_parsed() -> None:
    client, _ = make_client([_verdict_response(False, "excerpt does not mention this")])

    verdict = GroundingCritic(client, CONFIG).review(
        category="printing", urgency="low", rationale="x", cited_excerpts=[]
    )

    assert not verdict.grounded


def test_no_tool_call_is_a_critic_error() -> None:
    client, _ = make_client(
        [{"choices": [{"finish_reason": "stop", "message": {"content": "sorry"}}], "usage": {}}]
    )

    with pytest.raises(CriticError, match="did not call critic_verdict"):
        GroundingCritic(client, CONFIG).review(
            category="printing", urgency="low", rationale="x", cited_excerpts=[]
        )


def test_provider_error_is_a_critic_error() -> None:
    from triage.clock import FixedClock
    from triage.llm.client import LlmClient, LlmError

    from .conftest import NOW

    class FailingTransport:
        def send(self, payload: object, timeout_seconds: float) -> dict[str, object]:
            raise LlmError("500")

    client = LlmClient(FailingTransport(), "m", FixedClock(NOW))

    with pytest.raises(CriticError, match="provider error"):
        GroundingCritic(client, CONFIG).review(
            category="printing", urgency="low", rationale="x", cited_excerpts=[]
        )
