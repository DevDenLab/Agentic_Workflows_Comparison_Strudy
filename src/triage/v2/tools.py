"""The agent's four tools (docs/flows.md v2 step 7b). Each is read-only — the only write in v2 is
the ITSM create after the confidence gate, in the shell, never from inside the loop.

Every tool returns a `ToolResult`: `payload` is what the model sees (JSON), `source_ids` is what a
citation is allowed to name. The critic's code-level check (`v2/critic.py`) only accepts a citation
whose id appears in some `source_ids` actually returned during that run — the model cannot cite a
source it never retrieved.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from triage.llm.client import tool_schema
from triage.v1.cmdb import Cmdb
from triage.v1.rule_engine import RuleEngine
from triage.v2.guardrail import PiiGuardrail
from triage.v2.retrieval import SearchHit, SearchIndex

_SECTION = re.compile(r"^## (.+)$", re.MULTILINE)


def load_runbook_index(runbooks_dir: Path) -> SearchIndex:
    """Splits each runbook by its `## ` sections, so a citation points at one topic, not a file."""
    documents: list[tuple[str, str, dict[str, str]]] = []
    for path in sorted(runbooks_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        headers = [m.group(1) for m in _SECTION.finditer(text)]
        bodies = _SECTION.split(text)[
            2::2
        ]  # split() interleaves [prefix, h1, body1, h2, body2, ...]
        for header, body in zip(headers, bodies, strict=True):
            slug = re.sub(r"[^a-z0-9]+", "-", header.lower()).strip("-")
            documents.append(
                (
                    f"kb:{path.stem}#{slug}",
                    f"{header}\n{body.strip()}",
                    {"doc": path.name, "section": header},
                )
            )
    return SearchIndex(documents)


def load_history_index(history_path: Path) -> SearchIndex:
    import json

    documents: list[tuple[str, str, dict[str, str]]] = []
    for line in history_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        text = f"{record['subject']}\n{record['text']}"
        documents.append((f"similar_ticket:{record['ticket_id']}", text, record))
    return SearchIndex(documents)


@dataclass(frozen=True, slots=True)
class ToolResult:
    payload: dict[str, Any]
    source_ids: tuple[str, ...] = ()
    excerpts: dict[str, str] = field(default_factory=dict)
    """source_id -> the actual cited text, for the critic (v2/critic.py). Kept separate from
    `payload` because the model sees a token like <EMP_1>, but the excerpt for a citation should
    read naturally, e.g. "role: Charge Nurse" rather than repeating the raw payload."""


class Tool(Protocol):
    name: str

    def schema(self) -> dict[str, Any]: ...
    def run(self, arguments: dict[str, Any]) -> ToolResult: ...


class ToolError(Exception):
    """A tool call with bad arguments. Reported back to the model as a tool result, not raised."""


def _hits_payload(hits: list[SearchHit]) -> list[dict[str, Any]]:
    return [
        {"source_id": hit.doc_id, "score": round(hit.score, 3), "excerpt": hit.text[:600]}
        for hit in hits
    ]


class KbSearchTool:
    name = "kb_search"

    def __init__(self, index: SearchIndex) -> None:
        self._index = index

    def schema(self) -> dict[str, Any]:
        return tool_schema(
            self.name,
            "Search internal runbooks for troubleshooting guidance. Returns cited excerpts.",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for."},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        )

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        query = _require_str(arguments, "query")
        hits = self._index.search(query, k=3)
        return ToolResult(
            payload={"results": _hits_payload(hits)},
            source_ids=tuple(h.doc_id for h in hits),
            excerpts={h.doc_id: h.text[:600] for h in hits},
        )


class SimilarTicketsTool:
    name = "similar_tickets"

    def __init__(self, index: SearchIndex) -> None:
        self._index = index

    def schema(self) -> dict[str, Any]:
        return tool_schema(
            self.name,
            "Search resolved historical tickets for similar cases and how they were handled.",
            {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        )

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        query = _require_str(arguments, "query")
        hits = self._index.search(query, k=3)
        results = []
        excerpts: dict[str, str] = {}
        for hit in hits:
            record = hit.metadata
            results.append(
                {
                    "source_id": hit.doc_id,
                    "score": round(hit.score, 3),
                    "category": record.get("category"),
                    "priority": record.get("priority"),
                    "assignment_group": record.get("assignment_group"),
                    "resolution": record.get("resolution"),
                }
            )
            excerpts[hit.doc_id] = (
                f"{record.get('subject', '')}: {record.get('resolution', '')} "
                f"(resolved as {record.get('category')} / {record.get('priority')})"
            )
        return ToolResult(
            payload={"results": results},
            source_ids=tuple(h.doc_id for h in hits),
            excerpts=excerpts,
        )


class CmdbLookupTool:
    name = "cmdb_lookup"

    def __init__(self, cmdb: Cmdb, guardrail: PiiGuardrail) -> None:
        self._cmdb = cmdb
        self._guardrail = guardrail

    def schema(self) -> dict[str, Any]:
        return tool_schema(
            self.name,
            "Look up the requester and any asset named in the ticket in the CMDB. Pass tokens "
            "(like <EMP_1> or <EMAIL_1>) exactly as they appear in the ticket, not real values.",
            {
                "type": "object",
                "properties": {
                    "employee_id_or_token": {"type": "string"},
                    "email_or_token": {"type": "string"},
                    "asset_tag": {"type": "string"},
                },
                "additionalProperties": False,
            },
        )

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        employee_id = self._guardrail.detokenize(arguments.get("employee_id_or_token"))
        email = self._guardrail.detokenize(arguments.get("email_or_token"))
        asset_tag = arguments.get("asset_tag")
        if not any((employee_id, email, asset_tag)):
            raise ToolError(
                "provide at least one of employee_id_or_token, email_or_token, asset_tag"
            )

        context = self._cmdb.lookup(employee_id=employee_id, email=email, asset_tag=asset_tag)
        source_ids: list[str] = []
        excerpts: dict[str, str] = {}
        payload: dict[str, Any] = {"notes": list(context.notes)}

        if context.employee is not None:
            token = self._guardrail.retokenize(context.employee.employee_id)
            payload["employee"] = {"id_token": token, "role": context.employee.role}
            source_id = f"cmdb:employee/{context.employee.employee_id}"
            source_ids.append(source_id)
            department = (
                f", department: {context.department.name} "
                f"({'clinical' if context.department.clinical else 'non-clinical'})"
                if context.department
                else ""
            )
            excerpts[source_id] = f"role: {context.employee.role}{department}"
        if context.department is not None:
            payload["department"] = {
                "name": context.department.name,
                "clinical": context.department.clinical,
            }
        if context.services:
            payload["services"] = [
                {"name": s.name, "criticality": s.criticality.value} for s in context.services
            ]
        if context.asset is not None:
            payload["asset"] = {
                "type": context.asset.asset_type,
                "service": context.asset.service.name,
                "service_criticality": context.asset.service.criticality.value,
            }
            source_id = f"cmdb:asset/{context.asset.asset_tag}"
            source_ids.append(source_id)
            excerpts[source_id] = (
                f"{context.asset.asset_type}, supports {context.asset.service.name} "
                f"(criticality {context.asset.service.criticality.value})"
            )
        return ToolResult(payload=payload, source_ids=tuple(source_ids), excerpts=excerpts)


class ApplyRulesTool:
    """Bound to one ticket's (redacted) subject/text at construction — the model supplies no
    arguments, so it cannot get a different answer than v1's rule engine would give this exact
    ticket. This is the literal reuse: v1's rule engine, unmodified, callable from inside v2."""

    name = "apply_rules"

    def __init__(self, rule_engine: RuleEngine, subject: str, text: str) -> None:
        self._rule_engine = rule_engine
        self._subject = subject
        self._text = text

    def schema(self) -> dict[str, Any]:
        return tool_schema(
            self.name,
            "Run the conventional keyword rule engine (the same one v1 uses) on this ticket. "
            "Takes no arguments.",
            {"type": "object", "properties": {}, "additionalProperties": False},
        )

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        match = self._rule_engine.match(self._subject, self._text)
        if match is None:
            return ToolResult(payload={"matched": False})
        source_id = f"rule:{match.rule_id}"
        return ToolResult(
            payload={
                "matched": True,
                "source_id": source_id,
                "rule_id": match.rule_id,
                "category": match.category,
                "urgency": match.urgency.value,
                "matched_phrase": match.matched_phrase,
            },
            source_ids=(source_id,),
            excerpts={
                source_id: f"rule {match.rule_id} matched {match.matched_phrase!r} "
                f"-> category {match.category}, urgency {match.urgency.value}"
            },
        )


def _require_str(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"{key} must be a non-empty string")
    return value
