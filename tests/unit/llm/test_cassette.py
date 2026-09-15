from pathlib import Path
from typing import Any

import pytest

from triage.llm.cassette import CassetteTransport
from triage.llm.client import LlmError


class CountingTransport:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls = 0

    def send(self, payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
        self.calls += 1
        return self.response


PAYLOAD = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
RESPONSE = {"choices": [{"message": {"content": "ok"}}]}


def test_record_always_calls_inner_and_writes_a_cassette(tmp_path: Path) -> None:
    inner = CountingTransport(RESPONSE)
    transport = CassetteTransport(inner, tmp_path, mode="record")

    first = transport.send(PAYLOAD, 5)
    second = transport.send(PAYLOAD, 5)

    assert first == second == RESPONSE
    assert inner.calls == 2
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_replay_never_calls_inner(tmp_path: Path) -> None:
    inner = CountingTransport(RESPONSE)
    CassetteTransport(inner, tmp_path, mode="record").send(PAYLOAD, 5)
    inner.calls = 0

    result = CassetteTransport(inner, tmp_path, mode="replay").send(PAYLOAD, 5)

    assert result == RESPONSE
    assert inner.calls == 0


def test_replay_without_a_cassette_raises() -> None:
    inner = CountingTransport(RESPONSE)

    with pytest.raises(LlmError, match="no cassette"):
        CassetteTransport(inner, Path("does-not-matter"), mode="replay").send(PAYLOAD, 5)


def test_replay_or_record_calls_inner_only_once(tmp_path: Path) -> None:
    inner = CountingTransport(RESPONSE)
    transport = CassetteTransport(inner, tmp_path, mode="replay_or_record")

    for _ in range(3):
        assert transport.send(PAYLOAD, 5) == RESPONSE

    assert inner.calls == 1


def test_different_payloads_get_different_cassettes(tmp_path: Path) -> None:
    inner = CountingTransport(RESPONSE)
    transport = CassetteTransport(inner, tmp_path, mode="replay_or_record")

    transport.send(PAYLOAD, 5)
    transport.send({**PAYLOAD, "model": "other"}, 5)

    assert inner.calls == 2
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_key_does_not_depend_on_dict_ordering(tmp_path: Path) -> None:
    inner = CountingTransport(RESPONSE)
    transport = CassetteTransport(inner, tmp_path, mode="replay_or_record")

    transport.send({"a": 1, "b": 2}, 5)
    transport.send({"b": 2, "a": 1}, 5)

    assert inner.calls == 1
