"""The shared vocabulary. Every pipeline takes an `InboundMessage` and returns a `TriageResult`.

This package imports nothing else from `triage` (enforced by import-linter), so v1, v1.5, v2 and the
benchmark can all depend on it without depending on each other.
"""

from triage.contracts.decision import (
    AuditEvent,
    Citation,
    DecidedBy,
    Enrichment,
    Outcome,
    Priority,
    TriageDecision,
    TriageResult,
    Usage,
)
from triage.contracts.pipeline import TriagePipeline
from triage.contracts.taxonomy import Taxonomy, TaxonomyEntry
from triage.contracts.ticket import Channel, ExtractedFields, InboundMessage, Ticket

__all__ = [
    "AuditEvent",
    "Channel",
    "Citation",
    "DecidedBy",
    "Enrichment",
    "ExtractedFields",
    "InboundMessage",
    "Outcome",
    "Priority",
    "Taxonomy",
    "TaxonomyEntry",
    "Ticket",
    "TriageDecision",
    "TriagePipeline",
    "TriageResult",
    "Usage",
]
