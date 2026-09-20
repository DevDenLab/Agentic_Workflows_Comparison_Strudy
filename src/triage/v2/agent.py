"""Orchestrator Agent — docs/flows.md v2 step 7.

This is the one place in v2 where the model decides what happens next: which tool to call, how
many times, and when it is done. Everything upstream and downstream of `Orchestrator.run` is
ordinary, unit-testable code (docs/flows.md, "the organising idea").

The model always sees the same tools plus one more: `submit_decision`, which ends the loop. There
is no "escalate" choice here on purpose — the agent proposes a category and urgency and the reasons
for it; whether that gets auto-resolved is the confidence gate's job (v2/confidence.py), computed
from signals the shell can verify, not from anything the model asserts about itself.
"""

import json
from dataclasses import dataclass, field

from pydantic import Field

from triage.config import ConfigModel
from triage.contracts import Taxonomy
from triage.llm.client import LlmClient, LlmError, LlmMessage, ToolCall, tool_schema
from triage.v1.priority_matrix import Level
from triage.v2.budget import BudgetGovernor
from triage.v2.tools import Tool, ToolError

SUBMIT_TOOL = "submit_decision"


class AgentConfig(ConfigModel):
    """config/agent.yaml: agent section."""

    temperature: float = Field(ge=0, le=2)
    max_output_tokens: int = Field(gt=0)
    timeout_seconds: float = Field(gt=0)
    max_repair_attempts: int = Field(ge=0)
    max_tool_result_chars: int = Field(gt=0)
    extra_body: dict[str, object] = Field(default_factory=dict)


class AgentFailure(Exception):  # noqa: N818 - reads better without an Error suffix
    """The agent never reached a usable submission within its budget or repair allowance."""


@dataclass(frozen=True, slots=True)
class AgentDecision:
    category: str
    urgency: Level
    citations: tuple[str, ...]
    rationale: str


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    name: str
    arguments: dict[str, object]
    result_summary: str


@dataclass(frozen=True, slots=True)
class AgentRun:
    decision: AgentDecision
    seen_source_ids: frozenset[str]
    apply_rules_matched: bool | None
    """None if apply_rules was never called."""
    apply_rules_category: str | None
    apply_rules_rule_id: str | None
    retrieval_strength: float
    repair_attempts: int
    steps: int
    prompt_tokens: int
    completion_tokens: int
    tool_calls: tuple[ToolCallRecord, ...] = field(default_factory=tuple)
    source_excerpts: dict[str, str] = field(default_factory=dict)
    """source_id -> the actual cited text, for the critic. Only covers sources the agent actually
    retrieved this run, same universe as `seen_source_ids`."""


def _submit_schema(taxonomy: Taxonomy) -> dict[str, object]:
    return tool_schema(
        SUBMIT_TOOL,
        "Submit your final classification. Call this once you are done gathering evidence. "
        "citations must list every source_id from your tool calls that supports this decision.",
        {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": sorted(taxonomy.category_ids)},
                "urgency": {"type": "string", "enum": ["low", "medium", "high"]},
                "citations": {"type": "array", "items": {"type": "string"}},
                "rationale": {"type": "string", "description": "One or two sentences."},
            },
            "required": ["category", "urgency", "citations", "rationale"],
            "additionalProperties": False,
        },
    )


def _tool_message(call_id: str, payload: object) -> LlmMessage:
    return LlmMessage(role="tool", tool_call_id=call_id, content=json.dumps(payload))


class Orchestrator:
    """Stateless across tickets: `tools` is passed to `run`, not fixed here, because two of the
    four tools (apply_rules, cmdb_lookup) are bound to one ticket's redacted text and PII map."""

    def __init__(
        self, client: LlmClient, taxonomy: Taxonomy, config: AgentConfig, system_prompt: str
    ) -> None:
        self._client = client
        self._taxonomy = taxonomy
        self._config = config
        self._system_prompt = system_prompt

    def run(self, subject: str, text: str, tools: list[Tool], budget: BudgetGovernor) -> AgentRun:
        self._tools = {tool.name: tool for tool in tools}
        self._tool_schemas = [tool.schema() for tool in tools] + [_submit_schema(self._taxonomy)]
        messages = [
            LlmMessage(role="system", content=self._system_prompt),
            LlmMessage(role="user", content=f"Subject: {subject}\n\n{text}"),
        ]
        seen_source_ids: set[str] = set()
        source_excerpts: dict[str, str] = {}
        apply_rules_matched: bool | None = None
        apply_rules_category: str | None = None
        apply_rules_rule_id: str | None = None
        retrieval_strength = 0.0
        repair_attempts = 0
        prompt_tokens = completion_tokens = 0
        tool_calls: list[ToolCallRecord] = []

        while True:
            budget.check()
            try:
                result = self._client.complete(
                    messages=messages,
                    tools=self._tool_schemas,
                    tool_choice="auto",
                    temperature=self._config.temperature,
                    max_tokens=self._config.max_output_tokens,
                    timeout_seconds=self._config.timeout_seconds,
                    extra=self._config.extra_body,
                )
            except LlmError as exc:
                raise AgentFailure(f"provider error: {exc}") from exc
            budget.record(
                prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens
            )
            prompt_tokens += result.prompt_tokens
            completion_tokens += result.completion_tokens

            if not result.tool_calls:
                messages = [
                    *messages,
                    LlmMessage(role="assistant", content=result.content),
                    LlmMessage(
                        role="user",
                        content="Call a tool, or call submit_decision to finish. "
                        "You must not just reply with text.",
                    ),
                ]
                continue

            messages = [*messages, LlmMessage(role="assistant", tool_calls=result.tool_calls)]
            submission: ToolCall | None = None
            for call in result.tool_calls:
                if call.name == SUBMIT_TOOL:
                    submission = call
                    messages = [*messages, _tool_message(call.id, {"received": True})]
                    continue
                payload, source_ids, excerpts, summary = self._execute(call)
                seen_source_ids.update(source_ids)
                source_excerpts.update(excerpts)
                tool_calls.append(ToolCallRecord(call.name, call.arguments, summary))
                if call.name == "apply_rules" and isinstance(payload, dict):
                    apply_rules_matched = bool(payload.get("matched"))
                    apply_rules_category = payload.get("category")
                    apply_rules_rule_id = payload.get("rule_id")
                if call.name in ("kb_search", "similar_tickets") and isinstance(payload, dict):
                    scores = [r["score"] for r in payload.get("results", [])]
                    if scores:
                        retrieval_strength = max(retrieval_strength, max(scores))
                messages = [*messages, _tool_message(call.id, payload)]

            if submission is None:
                continue

            try:
                decision = self._validate_submission(submission.arguments)
            except ValueError as exc:
                repair_attempts += 1
                if repair_attempts > self._config.max_repair_attempts:
                    raise AgentFailure(f"exhausted repair attempts: {exc}") from exc
                messages = [
                    *messages,
                    LlmMessage(
                        role="user",
                        content=f"That submission was invalid: {exc}. Call submit_decision again.",
                    ),
                ]
                continue

            return AgentRun(
                decision=decision,
                seen_source_ids=frozenset(seen_source_ids),
                apply_rules_matched=apply_rules_matched,
                apply_rules_category=apply_rules_category,
                apply_rules_rule_id=apply_rules_rule_id,
                retrieval_strength=retrieval_strength,
                repair_attempts=repair_attempts,
                steps=budget.steps,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                tool_calls=tuple(tool_calls),
                source_excerpts=source_excerpts,
            )

    def _execute(self, call: ToolCall) -> tuple[object, tuple[str, ...], dict[str, str], str]:
        tool = self._tools.get(call.name)
        if tool is None:
            return {"error": f"unknown tool {call.name!r}"}, (), {}, "unknown tool"
        try:
            result = tool.run(call.arguments)
        except ToolError as exc:
            return {"error": str(exc)}, (), {}, f"error: {exc}"
        payload = _truncate(result.payload, self._config.max_tool_result_chars)
        return payload, result.source_ids, result.excerpts, json.dumps(payload)[:200]

    def _validate_submission(self, arguments: dict[str, object]) -> AgentDecision:
        try:
            category = str(arguments["category"])
            urgency = Level(str(arguments["urgency"]))
            citations_raw = arguments["citations"]
            rationale = str(arguments["rationale"])
        except (KeyError, ValueError) as exc:
            raise ValueError(f"malformed arguments: {exc}") from exc
        if category not in self._taxonomy.category_ids:
            raise ValueError(f"category {category!r} is not one of the allowed categories")
        if not isinstance(citations_raw, list) or not all(
            isinstance(c, str) for c in citations_raw
        ):
            raise ValueError("citations must be a list of strings")
        if not rationale.strip():
            raise ValueError("rationale must not be empty")
        return AgentDecision(category, urgency, tuple(citations_raw), rationale)


def _truncate(payload: dict[str, object], max_chars: int) -> dict[str, object]:
    text = json.dumps(payload)
    if len(text) <= max_chars:
        return payload
    return {"truncated": True, "preview": text[:max_chars]}
