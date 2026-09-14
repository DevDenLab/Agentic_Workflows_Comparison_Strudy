"""Step 8 — Priority Matrix: impact x urgency -> P1..P4, ITIL style.

Urgency comes from the matched rule. Impact comes from CMDB facts plus a few scope phrases.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from triage.config import ConfigModel, SemVer
from triage.contracts import Priority
from triage.v1.cmdb import CmdbContext, Criticality
from triage.v1.phrases import Phrase, compile_phrase


class Level(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


_RANK = {Level.LOW: 0, Level.MEDIUM: 1, Level.HIGH: 2}


class ImpactPolicy(ConfigModel):
    base: Level
    clinical_department: Level
    high_criticality_asset: Level
    widespread: Level
    widespread_phrases: tuple[Phrase, ...] = Field(min_length=1)


class PriorityMatrixConfig(ConfigModel):
    """config/priority_matrix.yaml"""

    version: SemVer
    matrix: dict[Level, dict[Level, Priority]]
    impact: ImpactPolicy

    @model_validator(mode="after")
    def _matrix_is_complete(self) -> Self:
        missing = [
            f"{impact}/{urgency}"
            for impact in Level
            for urgency in Level
            if urgency not in self.matrix.get(impact, {})
        ]
        if missing:
            raise ValueError(f"matrix is missing impact/urgency cells: {missing}")
        return self


@dataclass(frozen=True, slots=True)
class PriorityAssessment:
    impact: Level
    urgency: Level
    priority: Priority
    impact_reasons: tuple[str, ...]


class PriorityMatrix:
    def __init__(self, config: PriorityMatrixConfig) -> None:
        self._matrix = config.matrix
        self._policy = config.impact
        self._widespread = tuple(
            (phrase, compile_phrase(phrase)) for phrase in config.impact.widespread_phrases
        )

    def assess(
        self, *, urgency: Level, context: CmdbContext, subject: str, text: str
    ) -> PriorityAssessment:
        """Impact is the highest level any signal gives. Every signal at that level is a reason."""
        signals: list[tuple[Level, str]] = [(self._policy.base, "base impact")]
        if context.department is not None and context.department.clinical:
            signals.append(
                (
                    self._policy.clinical_department,
                    f"requester is in clinical department {context.department.department_id}",
                )
            )
        if context.asset is not None and context.asset.service.criticality is Criticality.HIGH:
            signals.append(
                (
                    self._policy.high_criticality_asset,
                    f"asset {context.asset.asset_tag} supports "
                    f"high-criticality service {context.asset.service.service_id}",
                )
            )
        haystack = f"{subject}\n{text}"
        phrase = next((p for p, pattern in self._widespread if pattern.search(haystack)), None)
        if phrase is not None:
            signals.append((self._policy.widespread, f"ticket says {phrase!r}"))

        impact = max((level for level, _ in signals), key=_RANK.__getitem__)
        return PriorityAssessment(
            impact=impact,
            urgency=urgency,
            priority=self._matrix[impact][urgency],
            impact_reasons=tuple(reason for level, reason in signals if level is impact),
        )
