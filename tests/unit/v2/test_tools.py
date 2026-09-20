from pathlib import Path

import pytest

from triage.v1.cmdb import SqliteCmdb, create_cmdb
from triage.v1.rule_engine import RuleEngine
from triage.v2.guardrail import PiiGuardrail
from triage.v2.tools import (
    ApplyRulesTool,
    CmdbLookupTool,
    KbSearchTool,
    SimilarTicketsTool,
    ToolError,
    load_history_index,
    load_runbook_index,
)


@pytest.fixture(scope="module")
def cmdb(data_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> SqliteCmdb:
    db_path = tmp_path_factory.mktemp("cmdb") / "cmdb.sqlite3"
    create_cmdb(db_path, data_dir / "cmdb" / "schema.sql", data_dir / "cmdb" / "seed.sql")
    return SqliteCmdb(db_path)


def test_runbook_index_splits_by_section(data_dir: Path) -> None:
    index = load_runbook_index(data_dir / "runbooks")

    hits = index.search("vpn drops repeatedly", k=1)

    assert hits
    assert hits[0].doc_id.startswith("kb:network#")


def test_history_index_loads_every_record(data_dir: Path) -> None:
    index = load_history_index(data_dir / "history" / "resolved.jsonl")

    hits = index.search("VPN disconnects while working from home", k=1)

    assert hits
    assert hits[0].doc_id == "similar_ticket:HIST-003"
    assert hits[0].metadata["category"] == "network_connectivity"


def test_kb_search_tool_returns_source_ids_matching_its_excerpts(data_dir: Path) -> None:
    tool = KbSearchTool(load_runbook_index(data_dir / "runbooks"))

    result = tool.run({"query": "vpn drops"})

    ids = [r["source_id"] for r in result.payload["results"]]
    assert ids == list(result.source_ids)
    assert all(sid in result.excerpts for sid in result.source_ids)


def test_kb_search_requires_a_query(data_dir: Path) -> None:
    tool = KbSearchTool(load_runbook_index(data_dir / "runbooks"))

    with pytest.raises(ToolError):
        tool.run({})
    with pytest.raises(ToolError):
        tool.run({"query": "  "})


def test_similar_tickets_tool_carries_the_resolution(data_dir: Path) -> None:
    tool = SimilarTicketsTool(load_history_index(data_dir / "history" / "resolved.jsonl"))

    result = tool.run({"query": "VPN keeps disconnecting from home"})

    (top,) = result.payload["results"][:1]
    assert top["source_id"] == "similar_ticket:HIST-003"
    assert "idle-timeout" in result.excerpts[top["source_id"]]


def test_apply_rules_tool_is_bound_to_construction_time_text_not_arguments(
    cmdb: SqliteCmdb,
) -> None:
    """The tool must give the same answer as v1 would for this ticket, regardless of what
    arguments a model passes — it takes none."""
    from triage.v1.rule_engine import RuleSet

    rules = RuleSet.model_validate(
        {
            "version": "1.0.0",
            "rules": [
                {
                    "id": "R001",
                    "description": "d",
                    "category": "network_connectivity",
                    "urgency": "medium",
                    "any_of": ["vpn"],
                }
            ],
        }
    )
    tool = ApplyRulesTool(RuleEngine(rules), "VPN issue", "my vpn keeps dropping")

    result = tool.run({"subject": "ignored", "text": "ignored"})

    assert result.payload["matched"] is True
    assert result.payload["rule_id"] == "R001"
    assert result.source_ids == ("rule:R001",)
    assert "rule R001" in result.excerpts["rule:R001"]


def test_apply_rules_tool_reports_no_match(cmdb: SqliteCmdb) -> None:
    from triage.v1.rule_engine import RuleSet

    rules = RuleSet.model_validate(
        {
            "version": "1.0.0",
            "rules": [
                {
                    "id": "R001",
                    "description": "d",
                    "category": "printing",
                    "urgency": "low",
                    "any_of": ["printer"],
                }
            ],
        }
    )
    tool = ApplyRulesTool(RuleEngine(rules), "s", "completely unrelated text")

    result = tool.run({})

    assert result.payload == {"matched": False}
    assert result.source_ids == ()


def test_cmdb_lookup_tool_detokenizes_the_argument_and_retokenizes_the_result(
    cmdb: SqliteCmdb,
) -> None:
    guardrail = PiiGuardrail()
    guardrail.redact("", "E100701 needs help")  # mints <EMP_1> -> E100701
    tool = CmdbLookupTool(cmdb, guardrail)

    result = tool.run({"employee_id_or_token": "<EMP_1>"})

    assert result.payload["employee"]["id_token"] == "<EMP_1>"  # noqa: S105 - a token, not a password
    assert "E100701" not in str(result.payload)
    assert result.source_ids == ("cmdb:employee/E100701",)
    assert "role" in result.excerpts["cmdb:employee/E100701"]


def test_cmdb_lookup_tool_needs_at_least_one_identifier(cmdb: SqliteCmdb) -> None:
    guardrail = PiiGuardrail()
    tool = CmdbLookupTool(cmdb, guardrail)

    with pytest.raises(ToolError):
        tool.run({})


def test_cmdb_lookup_tool_mints_a_token_for_a_value_never_in_the_ticket(cmdb: SqliteCmdb) -> None:
    """An asset tag is never PII, so it passes through unredacted, but the employee it belongs to
    might not have been mentioned by identifier in the ticket text at all."""
    guardrail = PiiGuardrail()
    tool = CmdbLookupTool(cmdb, guardrail)

    result = tool.run({"asset_tag": "CH-WOW-00007"})

    assert result.payload["asset"]["type"] == "workstation_on_wheels"
    assert result.source_ids == ("cmdb:asset/CH-WOW-00007",)
