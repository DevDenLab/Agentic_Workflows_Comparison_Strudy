"""Orchestrator.run: the ReAct loop, exercised with a scripted (non-network) transport."""

from typing import Any

import pytest

from triage.config import LoadedConfig
from triage.llm.client import LlmClient
from triage.v1.priority_matrix import Level
from triage.v2.agent import AgentConfig, AgentFailure, Orchestrator
from triage.v2.budget import BudgetConfig, BudgetGovernor
from triage.v2.tools import ToolError, ToolResult

from .conftest import NOW, make_client, text_response, tool_call_response

GENEROUS_BUDGET = BudgetConfig(max_steps=10, max_total_tokens=100_000, max_wall_seconds=300)


class FakeTool:
    def __init__(
        self, name: str, result: ToolResult | None = None, error: str | None = None
    ) -> None:
        self.name = name
        self._result = result
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {"name": self.name, "description": "d", "parameters": {"type": "object"}},
        }

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        self.calls.append(arguments)
        if self._error:
            raise ToolError(self._error)
        assert self._result is not None
        return self._result


def _budget() -> BudgetGovernor:
    from triage.clock import FixedClock

    return BudgetGovernor(GENEROUS_BUDGET, FixedClock(NOW))


def _orchestrator(
    client: LlmClient, loaded_config: LoadedConfig, config: AgentConfig
) -> Orchestrator:
    return Orchestrator(client, loaded_config.taxonomy, config, "system prompt")


def _submit_args(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "category": "network_connectivity",
        "urgency": "medium",
        "citations": ["kb:x#y"],
        "rationale": "matches the vpn runbook",
    }
    return base | overrides


SUBMIT: tuple[str, dict[str, object]] = ("submit_decision", _submit_args())


def test_a_tool_call_then_submit(agent_config: AgentConfig, loaded_config: LoadedConfig) -> None:
    client, transport = make_client(
        [
            tool_call_response(("kb_search", {"query": "vpn"})),
            tool_call_response(SUBMIT),
        ]
    )
    tool = FakeTool("kb_search", ToolResult(payload={"ok": True}, source_ids=("kb:x#y",)))

    run = _orchestrator(client, loaded_config, agent_config).run("s", "t", [tool], _budget())

    assert run.decision.category == "network_connectivity"
    assert run.decision.urgency is Level.MEDIUM
    assert run.decision.citations == ("kb:x#y",)
    assert run.seen_source_ids == frozenset({"kb:x#y"})
    assert run.steps == 2
    assert tool.calls == [{"query": "vpn"}]
    assert len(transport.payloads) == 2


def test_submit_in_the_same_turn_as_a_tool_call(
    agent_config: AgentConfig, loaded_config: LoadedConfig
) -> None:
    client, _ = make_client([tool_call_response(("kb_search", {"query": "vpn"}), SUBMIT)])
    tool = FakeTool("kb_search", ToolResult(payload={}, source_ids=("kb:x#y",)))

    run = _orchestrator(client, loaded_config, agent_config).run("s", "t", [tool], _budget())

    assert run.decision.category == "network_connectivity"
    assert run.steps == 1


def test_apply_rules_signals_are_captured(
    agent_config: AgentConfig, loaded_config: LoadedConfig
) -> None:
    client, _ = make_client([tool_call_response(("apply_rules", {}), SUBMIT)])
    tool = FakeTool(
        "apply_rules",
        ToolResult(
            payload={"matched": True, "category": "network_connectivity", "rule_id": "R040"},
            source_ids=("rule:R040",),
        ),
    )

    run = _orchestrator(client, loaded_config, agent_config).run("s", "t", [tool], _budget())

    assert run.apply_rules_matched is True
    assert run.apply_rules_category == "network_connectivity"
    assert run.apply_rules_rule_id == "R040"


def test_retrieval_strength_is_the_best_score_seen(
    agent_config: AgentConfig, loaded_config: LoadedConfig
) -> None:
    client, _ = make_client(
        [tool_call_response(("kb_search", {"query": "a"}), ("kb_search", {"query": "b"}), SUBMIT)]
    )
    tool = FakeTool(
        "kb_search",
        ToolResult(payload={"results": [{"score": 0.2}, {"score": 0.8}]}, source_ids=("kb:x#y",)),
    )

    run = _orchestrator(client, loaded_config, agent_config).run("s", "t", [tool], _budget())

    assert run.retrieval_strength == pytest.approx(0.8)


def test_invalid_submission_is_repaired_then_succeeds(
    agent_config: AgentConfig, loaded_config: LoadedConfig
) -> None:
    bad_submit = ("submit_decision", _submit_args(category="not_real"))
    client, transport = make_client([tool_call_response(bad_submit), tool_call_response(SUBMIT)])

    run = _orchestrator(client, loaded_config, agent_config).run("s", "t", [], _budget())

    assert run.decision.category == "network_connectivity"
    assert run.repair_attempts == 1
    assert "invalid" in transport.payloads[1]["messages"][-1]["content"].lower()


def test_exhausted_repair_attempts_raise_agent_failure(
    agent_config: AgentConfig, loaded_config: LoadedConfig
) -> None:
    bad_submit = ("submit_decision", _submit_args(category="nope"))
    client, _ = make_client([tool_call_response(bad_submit), tool_call_response(bad_submit)])

    with pytest.raises(AgentFailure, match="exhausted repair attempts"):
        _orchestrator(client, loaded_config, agent_config).run("s", "t", [], _budget())


def test_plain_text_with_no_tool_call_is_nudged_then_recovers(
    agent_config: AgentConfig, loaded_config: LoadedConfig
) -> None:
    client, transport = make_client([text_response("thinking..."), tool_call_response(SUBMIT)])

    run = _orchestrator(client, loaded_config, agent_config).run("s", "t", [], _budget())

    assert run.decision.category == "network_connectivity"
    assert "must not just reply" in transport.payloads[1]["messages"][-1]["content"]


def test_an_unknown_tool_name_is_reported_back_not_raised(
    agent_config: AgentConfig, loaded_config: LoadedConfig
) -> None:
    client, _ = make_client([tool_call_response(("no_such_tool", {})), tool_call_response(SUBMIT)])

    run = _orchestrator(client, loaded_config, agent_config).run("s", "t", [], _budget())

    assert run.decision.category == "network_connectivity"


def test_a_tool_error_is_reported_back_not_raised(
    agent_config: AgentConfig, loaded_config: LoadedConfig
) -> None:
    client, _ = make_client([tool_call_response(("kb_search", {})), tool_call_response(SUBMIT)])
    tool = FakeTool("kb_search", error="query must be a non-empty string")

    run = _orchestrator(client, loaded_config, agent_config).run("s", "t", [tool], _budget())

    assert run.decision.category == "network_connectivity"


def test_budget_exceeded_propagates_from_check(
    agent_config: AgentConfig, loaded_config: LoadedConfig
) -> None:
    from triage.clock import FixedClock
    from triage.v2.budget import BudgetExceeded

    tiny_budget = BudgetGovernor(
        BudgetConfig(max_steps=1, max_total_tokens=100_000, max_wall_seconds=300), FixedClock(NOW)
    )
    client, _ = make_client([tool_call_response(("kb_search", {})), tool_call_response(SUBMIT)])
    tool = FakeTool("kb_search", ToolResult(payload={}, source_ids=()))

    with pytest.raises(BudgetExceeded):
        _orchestrator(client, loaded_config, agent_config).run("s", "t", [tool], tiny_budget)


def test_a_provider_error_becomes_an_agent_failure(
    agent_config: AgentConfig, loaded_config: LoadedConfig
) -> None:
    from triage.llm.client import LlmError

    class FailingTransport:
        def send(self, payload: object, timeout_seconds: float) -> dict[str, object]:
            raise LlmError("503")

    from triage.clock import FixedClock
    from triage.llm.client import LlmClient

    client = LlmClient(FailingTransport(), "m", FixedClock(NOW))

    with pytest.raises(AgentFailure, match="provider error"):
        _orchestrator(client, loaded_config, agent_config).run("s", "t", [], _budget())
