import json
from datetime import UTC, datetime
from typing import Any

import pytest

from triage.clock import FixedClock
from triage.llm.client import LlmClient
from triage.v2.agent import AgentConfig

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


def tool_call_response(*calls: tuple[str, dict[str, object]]) -> dict[str, Any]:
    """One assistant turn making one or more tool calls: ("tool_name", {arguments}) pairs."""
    return {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "tool_calls": [
                        {
                            "id": f"call_{i}",
                            "function": {"name": name, "arguments": json.dumps(args)},
                        }
                        for i, (name, args) in enumerate(calls)
                    ]
                },
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }


def text_response(content: str) -> dict[str, Any]:
    return {
        "choices": [{"finish_reason": "stop", "message": {"content": content}}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 10},
    }


@pytest.fixture
def agent_config() -> AgentConfig:
    return AgentConfig(
        temperature=0.0,
        max_output_tokens=200,
        timeout_seconds=10,
        max_repair_attempts=1,
        max_tool_result_chars=5000,
    )


def make_client(responses: list[dict[str, Any]]) -> tuple[LlmClient, ScriptedTransport]:
    transport = ScriptedTransport(responses)
    return LlmClient(transport, "deepseek-flash", FixedClock(NOW)), transport
