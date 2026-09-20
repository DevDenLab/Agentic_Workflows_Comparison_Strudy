"""v2 end to end: real config, real SQLite, real CMDB, real runbook/history indices, scripted
(non-network) transports for the agent and critic."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from triage.clock import FixedClock
from triage.config import Settings
from triage.container import AgentRuntime, Container, build_agent, build_container
from triage.contracts import Channel, DecidedBy, InboundMessage, Outcome, Priority, TriagePipeline
from triage.llm.client import LlmClient, LlmError

NOW = datetime(2026, 9, 14, 15, 0, tzinfo=UTC)


class ScriptedTransport:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.payloads: list[dict[str, Any]] = []

    def send(self, payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
        self.payloads.append(payload)
        if not self._responses:
            raise LlmError("no response scripted: simulated provider outage")
        return self._responses.pop(0)


def tool_call(*calls: tuple[str, dict[str, object]]) -> dict[str, Any]:
    return {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "tool_calls": [
                        {"id": f"c{i}", "function": {"name": n, "arguments": json.dumps(a)}}
                        for i, (n, a) in enumerate(calls)
                    ]
                },
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }


def verdict(grounded: bool, reason: str = "ok") -> dict[str, Any]:
    return {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "tool_calls": [
                        {
                            "id": "v1",
                            "function": {
                                "name": "critic_verdict",
                                "arguments": json.dumps({"grounded": grounded, "reason": reason}),
                            },
                        }
                    ]
                },
            }
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 5},
    }


def submit(
    category: str, urgency: str, citations: list[str], rationale: str = "because"
) -> tuple[str, dict[str, object]]:
    args: dict[str, object] = {
        "category": category,
        "urgency": urgency,
        "citations": citations,
        "rationale": rationale,
    }
    return ("submit_decision", args)


def _container(config_dir: Path, data_dir: Path, var_dir: Path) -> Container:
    settings = Settings(
        _env_file=None,
        config_dir=config_dir,
        data_dir=data_dir,
        var_dir=var_dir,
        log_level="WARNING",
    )
    return build_container(settings, clock=FixedClock(NOW))


def _agent(
    container: Container,
    agent_responses: list[dict[str, Any]],
    critic_responses: list[dict[str, Any]],
) -> tuple[AgentRuntime, ScriptedTransport]:
    agent_transport = ScriptedTransport(agent_responses)
    critic_transport = ScriptedTransport(critic_responses)
    llm = LlmClient(agent_transport, "deepseek-flash", container.clock)
    critic = LlmClient(critic_transport, "deepseek-flash", container.clock)
    return build_agent(container, llm, critic, sleep=lambda _: None), agent_transport


@pytest.fixture
def container(config_dir: Path, data_dir: Path, tmp_path: Path) -> Container:
    return _container(config_dir, data_dir, tmp_path / "var")


def _web_form(
    body: str, message_id: str = "webform:F-1", sender: str = "kevin.nguyen@contoso.example"
) -> InboundMessage:
    return InboundMessage(
        message_id=message_id,
        channel=Channel.WEB_FORM,
        received_at=NOW,
        sender=sender,
        subject="Help",
        raw_body=body,
    )


def test_pipeline_satisfies_the_shared_contract(container: Container) -> None:
    agent, _ = _agent(container, [], [])
    assert isinstance(agent.pipeline, TriagePipeline)


def test_high_confidence_agreement_auto_resolves(container: Container) -> None:
    """apply_rules agrees with the agent's own category -> high confidence -> auto-resolve."""
    agent, transport = _agent(
        container,
        [
            tool_call(("apply_rules", {})),
            tool_call(submit("network_connectivity", "medium", ["rule:R040"])),
        ],
        [verdict(True, "the rule match supports this")],
    )

    result = agent.pipeline.triage(_web_form("My VPN disconnects every 10 minutes."))

    assert result.outcome is Outcome.AUTO_RESOLVED
    assert result.decided_by is DecidedBy.AGENT
    decision = result.decision
    assert decision is not None
    assert decision.category == "network_connectivity"
    assert decision.confidence > 0.55
    assert agent.itsm.count() == 1
    assert len(transport.payloads) == 2  # apply_rules step, then submit


def test_no_evidence_and_no_rule_agreement_escalates_with_draft_and_evidence(
    container: Container,
) -> None:
    agent, _ = _agent(
        container,
        [tool_call(submit("access_identity", "low", []))],
        [],  # no citations -> code-level grounding fails -> critic is never called
    )

    result = agent.pipeline.triage(_web_form("It's broken again."))

    assert result.outcome is Outcome.HUMAN_REVIEW
    assert result.decided_by is DecidedBy.AGENT
    assert result.decision is not None  # the draft is attached, not a raw ticket
    assert result.decision.category == "access_identity"
    assert result.decision.confidence == 0.0
    (queued,) = agent.human_queue.items()
    assert queued.draft is not None
    assert agent.itsm.count() == 0


def test_citing_a_source_never_retrieved_fails_the_code_level_check(container: Container) -> None:
    agent, _ = _agent(
        container,
        [tool_call(submit("printing", "low", ["kb:fabricated#nonexistent"]))],
        [],
    )

    result = agent.pipeline.triage(_web_form("Printer issue."))

    assert result.outcome is Outcome.HUMAN_REVIEW
    ungrounded_events = [e for e in result.audit if e.event == "ungrounded_citations"]
    assert ungrounded_events
    unknown = ungrounded_events[0].detail["unknown"]
    assert isinstance(unknown, list)
    assert "kb:fabricated#nonexistent" in unknown


def test_critic_disagreeing_forces_escalation_even_with_a_citation(container: Container) -> None:
    agent, _ = _agent(
        container,
        [
            tool_call(("kb_search", {"query": "printer"})),
            tool_call(submit("printing", "low", ["kb:printing#nothing-prints-queue-looks-stuck"])),
        ],
        [verdict(False, "the excerpt is about a stuck queue, not this ticket")],
    )

    result = agent.pipeline.triage(_web_form("My screen flickers sometimes."))

    assert result.outcome is Outcome.HUMAN_REVIEW
    reviewed = [e for e in result.audit if e.event == "reviewed"]
    assert reviewed[0].detail["grounded"] is False


def test_security_incident_never_auto_resolves_even_at_full_confidence(
    container: Container,
) -> None:
    agent, _ = _agent(
        container,
        [
            tool_call(("apply_rules", {})),
            tool_call(submit("security_incident", "high", ["rule:R001"])),
        ],
        [verdict(True, "clear rule match")],
    )

    result = agent.pipeline.triage(_web_form("I think I clicked a phishing link."))

    assert result.outcome is Outcome.HUMAN_REVIEW
    assert result.decision is not None
    assert result.decision.category == "security_incident"


def test_agent_failure_falls_back_to_v1_rules_and_still_auto_resolves(container: Container) -> None:
    """No responses queued at all -> the very first LLM call errors -> AgentFailure -> fallback."""
    agent, _ = _agent(container, [], [])

    result = agent.pipeline.triage(_web_form("My VPN disconnects every 10 minutes."))

    assert result.outcome is Outcome.AUTO_RESOLVED
    assert result.decided_by is DecidedBy.RULES_FALLBACK
    assert result.decision is not None
    assert result.decision.category == "network_connectivity"
    assert result.decision.confidence == 1.0
    failed = [e for e in result.audit if e.event == "failed"]
    assert failed


def test_agent_failure_with_no_rule_match_escalates(container: Container) -> None:
    agent, _ = _agent(container, [], [])

    result = agent.pipeline.triage(_web_form("Something odd happened, not sure what."))

    assert result.outcome is Outcome.HUMAN_REVIEW
    assert result.escalation_reason is not None
    assert "agent unavailable" in result.escalation_reason


def test_duplicate_message_is_not_processed_twice(container: Container) -> None:
    agent, _ = _agent(
        container,
        [
            tool_call(("apply_rules", {})),
            tool_call(submit("network_connectivity", "medium", ["rule:R040"])),
        ],
        [verdict(True)],
    )
    message = _web_form("My VPN disconnects every 10 minutes.", message_id="webform:dup")

    agent.pipeline.triage(message)
    again = agent.pipeline.triage(message)

    assert again.outcome is Outcome.DUPLICATE
    assert agent.itsm.count() == 1


def test_pii_tokens_never_reach_the_model(container: Container) -> None:
    agent, transport = _agent(
        container,
        [tool_call(submit("access_identity", "low", []))],
        [],
    )

    agent.pipeline.triage(
        _web_form(
            "My employee id is E100701, please reset my password.",
            sender="kevin.nguyen@contoso.example",
        )
    )

    sent_text = json.dumps(transport.payloads[0])
    assert "E100701" not in sent_text
    assert "kevin.nguyen@contoso.example" not in sent_text
    assert "<EMP_1>" in sent_text


def test_clinical_department_raises_impact_the_same_way_as_v1(container: Container) -> None:
    agent, _ = _agent(
        container,
        [
            tool_call(("apply_rules", {})),
            tool_call(submit("network_connectivity", "high", ["rule:R041"])),
        ],
        [verdict(True)],
    )

    result = agent.pipeline.triage(
        InboundMessage(
            message_id="m-icu",
            channel=Channel.EMAIL,
            received_at=NOW,
            sender="priya.raman@contoso.example",  # ICU, clinical, per the CMDB seed
            subject="Wifi",
            raw_body="The wireless network here keeps cutting out during my shift.",
        )
    )

    assert result.decision is not None
    assert result.decision.priority is Priority.P2  # medium impact (clinical) x high urgency
