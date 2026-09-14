"""Output side of the contract: the decision, and the result envelope every pipeline returns."""

from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from triage.contracts._base import ContractModel, NonEmptyStr, TaxonomyId


class Priority(StrEnum):
    """ITIL priority, derived from impact x urgency."""

    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class Outcome(StrEnum):
    AUTO_RESOLVED = "auto_resolved"
    """Triaged and routed with no human in the loop. The incident itself is not fixed."""
    HUMAN_REVIEW = "human_review"
    DUPLICATE = "duplicate"
    DEAD_LETTER = "dead_letter"


class DecidedBy(StrEnum):
    """Who produced the decision. This is what the benchmark groups by."""

    RULES = "rules"
    LLM_NODE = "llm_node"
    AGENT = "agent"
    RULES_FALLBACK = "rules_fallback"


class Citation(ContractModel):
    source_id: NonEmptyStr = Field(
        description="'kb:<doc>#<chunk>', 'rule:<id>', 'cmdb:<table>/<key>' or 'ticket:<id>'."
    )
    quote: str | None = None


class Enrichment(ContractModel):
    department: str | None = None
    service: str | None = None
    asset_tag: str | None = None


class TriageDecision(ContractModel):
    category: TaxonomyId
    priority: Priority
    assignment_group: TaxonomyId
    enrichment: Enrichment = Field(default_factory=Enrichment)
    sla_due_at: AwareDatetime | None = None
    draft_response: NonEmptyStr
    confidence: float = Field(ge=0.0, le=1.0)
    citations: tuple[Citation, ...] = ()


class Usage(ContractModel):
    llm_calls: int = Field(default=0, ge=0)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    agent_steps: int = Field(default=0, ge=0)
    latency_ms: float = Field(ge=0.0)


class AuditEvent(ContractModel):
    at: AwareDatetime
    component: NonEmptyStr = Field(
        description="Diagram component id, e.g. 'rule_engine', 'critic'."
    )
    event: NonEmptyStr
    detail: dict[str, JsonValue] = Field(default_factory=dict)


class TriageResult(ContractModel):
    correlation_id: UUID
    message_id: NonEmptyStr
    pipeline: NonEmptyStr
    outcome: Outcome
    decision: TriageDecision | None
    decided_by: DecidedBy | None
    escalation_reason: str | None = None
    usage: Usage
    audit: tuple[AuditEvent, ...] = ()

    @model_validator(mode="after")
    def _outcome_is_consistent(self) -> Self:
        if (self.decision is None) != (self.decided_by is None):
            raise ValueError("decision and decided_by must both be set or both be None")
        if self.outcome is Outcome.AUTO_RESOLVED and self.decision is None:
            raise ValueError("auto_resolved requires a decision")
        if self.outcome is Outcome.HUMAN_REVIEW and not self.escalation_reason:
            raise ValueError("human_review requires an escalation_reason")
        return self
