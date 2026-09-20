"""Confidence Gate — docs/flows.md v2 step 10.

Deliberately does NOT use the model's own stated confidence: a number the model invents about
itself is not evidence. Every input here is something the shell can verify independently:
  - critic_grounded: the citation check passed (code) and an LLM pass agreed every claim is
    supported by its cited text (v2/critic.py). A hard gate — an ungrounded decision scores 0
    regardless of everything else.
  - apply_rules_agreement: True if the agent called apply_rules, it matched, and the agent's own
    category agrees; False if it matched and disagrees; None if apply_rules wasn't called or found
    nothing. Agreement with the deterministic rule engine is the strongest evidence available,
    because it is itself exact and auditable.
  - retrieval_strength: the best similarity score seen across every kb_search/similar_tickets call
    this run, 0 if neither was ever called or nothing scored above the search floor.
  - repair_attempts: schema-gate repairs the submission needed. Each one is a small penalty — a
    decision that took repair to even become well-formed is less trustworthy.

All of this is a pure function of typed inputs, so it is unit-tested exhaustively rather than
"trusted."
"""

from dataclasses import dataclass

from pydantic import Field

from triage.config import ConfigModel
from triage.contracts import Priority

# Weights and the threshold are a documented, tunable policy — not physics. Anyone re-running the
# benchmark after changing config/agent.yaml gets a different, honestly-different, number.
_AGREEMENT_BASE = {True: 0.6, False: 0.1, None: 0.3}
_RETRIEVAL_WEIGHT = 0.35
_REPAIR_PENALTY = 0.1


class ConfidenceConfig(ConfigModel):
    """config/agent.yaml: confidence section."""

    threshold: float = Field(ge=0, le=1)
    high_blast_radius_categories: tuple[str, ...] = ()
    """Escalate no matter how confident the agent is — a wrong auto-resolve here costs too much."""


@dataclass(frozen=True, slots=True)
class ConfidenceSignals:
    critic_grounded: bool
    apply_rules_agreement: bool | None
    retrieval_strength: float
    repair_attempts: int


def compute_confidence(signals: ConfidenceSignals) -> float:
    if not signals.critic_grounded:
        return 0.0
    score = (
        _AGREEMENT_BASE[signals.apply_rules_agreement]
        + _RETRIEVAL_WEIGHT * signals.retrieval_strength
        - _REPAIR_PENALTY * signals.repair_attempts
    )
    return max(0.0, min(1.0, score))


def may_auto_resolve(
    confidence: float, category: str, priority: Priority, config: ConfidenceConfig
) -> bool:
    if category in config.high_blast_radius_categories:
        return False
    if priority is Priority.P1:
        return False
    return confidence >= config.threshold
