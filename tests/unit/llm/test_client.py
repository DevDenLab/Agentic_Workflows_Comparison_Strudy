import json
from datetime import UTC, datetime
from typing import Any

import pytest

from triage.clock import FixedClock
from triage.llm.client import LlmClient, LlmError, LlmMessage, tool_schema

NOW = datetime(2026, 9, 14, 15, 0, tzinfo=UTC)


class FakeTransport:
    """Captures the last payload sent and returns a scripted response (or raises)."""

    def __init__(
        self, response: dict[str, Any] | None = None, error: Exception | None = None
    ) -> None:
        self.response = response
        self.error = error
        self.sent: dict[str, Any] | None = None
        self.timeout_seconds: float | None = None

    def send(self, payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
        self.sent = payload
        self.timeout_seconds = timeout_seconds
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def _response(**tool_args: object) -> dict[str, Any]:
    return {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "classify_ticket",
                                "arguments": json.dumps(tool_args),
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 18},
    }


def _client(transport: FakeTransport) -> LlmClient:
    return LlmClient(transport, "deepseek-flash", FixedClock(NOW))


def test_tool_call_is_parsed_with_usage_and_latency() -> None:
    transport = FakeTransport(_response(category="printing", urgency="low", confidence=0.9))
    clock = FixedClock(NOW)
    clock.advance(0.25)

    result = LlmClient(transport, "deepseek-flash", clock).complete(
        messages=[LlmMessage(role="user", content="hi")],
        tools=[tool_schema("classify_ticket", "d", {"type": "object"})],
        tool_choice="classify_ticket",
        temperature=0.0,
        max_tokens=100,
        timeout_seconds=10,
    )

    (call,) = result.tool_calls
    assert call.name == "classify_ticket"
    assert call.arguments == {"category": "printing", "urgency": "low", "confidence": 0.9}
    assert (result.prompt_tokens, result.completion_tokens) == (120, 18)
    assert result.finish_reason == "tool_calls"


def test_payload_carries_forced_tool_choice_and_optional_seed() -> None:
    transport = FakeTransport(_response(category="printing", urgency="low", confidence=0.9))

    _client(transport).complete(
        messages=[LlmMessage(role="system", content="s"), LlmMessage(role="user", content="u")],
        tools=[tool_schema("classify_ticket", "d", {"type": "object"})],
        tool_choice="classify_ticket",
        temperature=0.0,
        max_tokens=50,
        timeout_seconds=5,
        seed=7,
    )

    assert transport.sent is not None
    assert transport.sent["tool_choice"] == {
        "type": "function",
        "function": {"name": "classify_ticket"},
    }
    assert transport.sent["seed"] == 7
    assert transport.sent["messages"] == [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
    ]
    assert transport.timeout_seconds == 5


def test_seed_omitted_when_not_given() -> None:
    transport = FakeTransport(_response(category="printing", urgency="low", confidence=0.9))

    _client(transport).complete(
        messages=[LlmMessage(role="user", content="u")],
        temperature=0.0,
        max_tokens=50,
        timeout_seconds=5,
    )

    assert transport.sent is not None
    assert "seed" not in transport.sent
    assert "tools" not in transport.sent


def test_transport_error_becomes_llm_error() -> None:
    transport = FakeTransport(error=LlmError("503: unavailable"))

    with pytest.raises(LlmError, match="unavailable"):
        _client(transport).complete(
            messages=[LlmMessage(role="user", content="u")],
            temperature=0.0,
            max_tokens=50,
            timeout_seconds=5,
        )


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"choices": []},
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {"id": "1", "function": {"name": "x", "arguments": "{bad json"}}
                        ]
                    }
                }
            ]
        },
    ],
)
def test_malformed_response_is_an_llm_error(response: dict[str, Any]) -> None:
    with pytest.raises(LlmError):
        _client(FakeTransport(response)).complete(
            messages=[LlmMessage(role="user", content="u")],
            temperature=0.0,
            max_tokens=50,
            timeout_seconds=5,
        )


def test_no_tool_calls_is_not_an_error() -> None:
    """An assistant message with no tool_calls key at all is valid, just empty."""
    response = {
        "choices": [{"finish_reason": "stop", "message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2},
    }

    result = _client(FakeTransport(response)).complete(
        messages=[LlmMessage(role="user", content="u")],
        temperature=0.0,
        max_tokens=50,
        timeout_seconds=5,
    )

    assert result.tool_calls == ()
    assert result.content == "hello"
