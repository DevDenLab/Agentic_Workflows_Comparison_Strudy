import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from triage.clock import Clock, FixedClock
from triage.config import LoadedConfig
from triage.hybrid.classifier import LlmClassifier, LlmConfig
from triage.llm.client import LlmClient


class ScriptedTransport:
    """Returns one canned /chat/completions response per call, in order."""

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


@pytest.fixture
def llm_config() -> LlmConfig:
    return LlmConfig(
        version="1.0.0",
        temperature=0.0,
        max_output_tokens=200,
        timeout_seconds=10,
        max_repair_attempts=2,
        seed=7,
    )


@pytest.fixture
def prompts_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "prompts"


def make_classifier(
    responses: list[dict[str, Any]],
    llm_config: LlmConfig,
    loaded_config: LoadedConfig,
    prompts_dir: Path,
    clock: Clock | None = None,
) -> tuple[LlmClassifier, ScriptedTransport]:
    transport = ScriptedTransport(responses)
    client = LlmClient(
        transport, "deepseek-flash", clock or FixedClock(datetime(2026, 9, 14, 15, tzinfo=UTC))
    )
    return (
        LlmClassifier(
            client, llm_config, loaded_config.taxonomy, prompts_dir, loaded_config.app.organisation
        ),
        transport,
    )
