"""A minimal OpenAI-compatible /chat/completions client: forced single tool calls (v1.5's
classifier) and full multi-turn tool-calling conversations (v2's agent loop).

Swapping providers is a base URL and model change — DeepSeek, OpenRouter, Ollama and vLLM all speak
this shape. `Transport` is the seam tests and record/replay (cassette.py) plug into.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict

from triage.clock import Clock


class ToolCall(BaseModel):
    """A tool invocation: parsed out of a model response, or echoed back into the next request
    as part of the assistant turn that made it (multi-turn tool calling)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    arguments: dict[str, Any]


class LlmMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    """Assistant turns only: the tool calls that turn made."""
    tool_call_id: str | None = None
    """Tool turns only: which assistant tool_call this result answers."""

    def to_wire(self) -> dict[str, Any]:
        wire: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            wire["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                }
                for call in self.tool_calls
            ]
        if self.tool_call_id is not None:
            wire["tool_call_id"] = self.tool_call_id
        return wire


@dataclass(frozen=True, slots=True)
class ChatResult:
    tool_calls: tuple[ToolCall, ...]
    content: str | None
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    finish_reason: str | None


class LlmError(Exception):
    """The provider returned an HTTP error, a malformed response, or the request timed out."""


class Transport(Protocol):
    """One HTTP round-trip to a /chat/completions-shaped endpoint."""

    def send(self, payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]: ...


class HttpxTransport:
    def __init__(self, base_url: str, api_key: str) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"), headers={"Authorization": f"Bearer {api_key}"}
        )

    def send(self, payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
        try:
            response = self._client.post("/chat/completions", json=payload, timeout=timeout_seconds)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LlmError(f"{exc.response.status_code}: {exc.response.text[:500]}") from exc
        except httpx.HTTPError as exc:
            raise LlmError(str(exc)) from exc
        try:
            return dict(response.json())
        except json.JSONDecodeError as exc:
            raise LlmError(f"response was not JSON: {exc}") from exc

    def close(self) -> None:
        self._client.close()


def tool_schema(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters},
    }


class LlmClient:
    def __init__(self, transport: Transport, model: str, clock: Clock) -> None:
        self._transport = transport
        self._model = model
        self._clock = clock

    def complete(
        self,
        *,
        messages: Sequence[LlmMessage],
        tools: Sequence[dict[str, Any]] = (),
        tool_choice: str | Literal["auto"] | None = None,
        temperature: float,
        max_tokens: int,
        timeout_seconds: float,
        seed: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> ChatResult:
        """`tool_choice`: a tool name forces that call; "auto" lets the model choose or stop;
        None omits tools/tool_choice from the request entirely."""
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [m.to_wire() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = list(tools)
        if tool_choice == "auto":
            payload["tool_choice"] = "auto"
        elif tool_choice is not None:
            payload["tool_choice"] = {"type": "function", "function": {"name": tool_choice}}
        if seed is not None:
            payload["seed"] = seed
        if extra:
            payload.update(extra)

        started = self._clock.monotonic()
        raw = self._transport.send(payload, timeout_seconds)
        elapsed_ms = (self._clock.monotonic() - started) * 1000
        return _parse(raw, elapsed_ms)


def _parse(raw: dict[str, Any], latency_ms: float) -> ChatResult:
    try:
        choice = raw["choices"][0]
        message = choice["message"]
        usage = raw.get("usage") or {}
        tool_calls = tuple(
            ToolCall(
                id=call["id"],
                name=call["function"]["name"],
                arguments=json.loads(call["function"]["arguments"]),
            )
            for call in message.get("tool_calls") or []
        )
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise LlmError(f"malformed response: {exc}: {raw!r:.500}") from exc
    return ChatResult(
        tool_calls=tool_calls,
        content=message.get("content"),
        prompt_tokens=int(usage.get("prompt_tokens", 0)),
        completion_tokens=int(usage.get("completion_tokens", 0)),
        latency_ms=latency_ms,
        finish_reason=choice.get("finish_reason"),
    )
