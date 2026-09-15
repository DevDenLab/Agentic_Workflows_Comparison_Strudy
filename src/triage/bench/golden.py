"""Golden set: the labelled tickets every pipeline is graded against.

Labels follow docs/labelling-guide.md, written from service-desk policy, not from rules.yaml.
Files are data/golden/{in_dist,ood,adversarial}.yaml, each shaped `{split: ..., cases: [...]}`.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from triage.config import ConfigError, load_model
from triage.contracts import Channel, NonEmptyStr, Priority, Taxonomy, TaxonomyId


class Split(StrEnum):
    IN_DIST = "in_dist"
    OOD = "ood"
    ADVERSARIAL = "adversarial"


SPLIT_FILES = {
    Split.IN_DIST: "in_dist.yaml",
    Split.OOD: "ood.yaml",
    Split.ADVERSARIAL: "adversarial.yaml",
}
_ID_PREFIX = {Split.IN_DIST: "IND", Split.OOD: "OOD", Split.ADVERSARIAL: "ADV"}


class Subtype(StrEnum):
    STANDARD = "standard"
    PROMPT_INJECTION = "prompt_injection"
    PII = "pii"
    MULTI_ISSUE = "multi_issue"
    AMBIGUOUS = "ambiguous"
    MUST_ESCALATE = "must_escalate"


class Handling(StrEnum):
    AUTO = "auto"
    """Auto-resolving with the right labels is correct. Escalating earns no credit."""
    ESCALATE = "escalate"
    """Only escalating is correct. Auto-resolving is a confident error, whatever the labels."""


Level = Literal["low", "medium", "high"]


class _GoldenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GoldenInput(_GoldenModel):
    channel: Channel
    sender: NonEmptyStr
    subject: str
    body: NonEmptyStr


class Alternative(_GoldenModel):
    """A second defensible reading of an ambiguous ticket (guide A1). Also scored as correct."""

    category: TaxonomyId
    assignment_group: TaxonomyId
    priority: Priority


class GoldenLabel(_GoldenModel):
    category: TaxonomyId | None
    impact: Level | None
    urgency: Level | None
    priority: Priority | None
    assignment_group: TaxonomyId | None
    handling: Handling
    alternatives: tuple[Alternative, ...] = ()

    @property
    def determinable(self) -> bool:
        return self.category is not None

    @model_validator(mode="after")
    def _all_or_nothing(self) -> Self:
        values = (self.category, self.impact, self.urgency, self.priority, self.assignment_group)
        nulls = [value is None for value in values]
        if any(nulls) and not all(nulls):
            raise ValueError(
                "category, impact, urgency, priority and assignment_group "
                "must all be set or all null"
            )
        if all(nulls):
            if self.handling is not Handling.ESCALATE:
                raise ValueError("an undeterminable ticket (null labels) needs handling: escalate")
            if self.alternatives:
                raise ValueError("an undeterminable ticket cannot have alternatives")
        return self


class GoldenCase(_GoldenModel):
    id: str = Field(pattern=r"^(IND|OOD|ADV)-\d{3}$")
    split: Split
    subtype: Subtype
    input: GoldenInput
    label: GoldenLabel
    rationale: NonEmptyStr

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        prefix = _ID_PREFIX[self.split]
        if not self.id.startswith(f"{prefix}-"):
            raise ValueError(f"{self.id}: ids in the {self.split} split start with {prefix}-")
        if (self.split is Split.ADVERSARIAL) == (self.subtype is Subtype.STANDARD):
            raise ValueError(
                f"{self.id}: adversarial cases need a specific subtype; other splits use 'standard'"
            )
        if self.subtype is Subtype.MUST_ESCALATE and self.label.handling is not Handling.ESCALATE:
            raise ValueError(f"{self.id}: must_escalate cases need handling: escalate")
        if not self.label.determinable and self.subtype is not Subtype.AMBIGUOUS:
            raise ValueError(f"{self.id}: only ambiguous cases may have null labels")
        return self

    def violations(self, taxonomy: Taxonomy) -> list[str]:
        readings = [(self.label.category, self.label.assignment_group)]
        readings += [(alt.category, alt.assignment_group) for alt in self.label.alternatives]
        problems: list[str] = []
        for category, group in readings:
            if category is not None and category not in taxonomy.category_ids:
                problems.append(f"{self.id}: category {category!r} is not in the taxonomy")
            if group is not None and group not in taxonomy.group_ids:
                problems.append(f"{self.id}: assignment_group {group!r} is not in the taxonomy")
        return problems


class GoldenFile(_GoldenModel):
    split: Split
    reviewed_by: str | None = None
    """The human who checked every label in this file. None while the labels are a draft."""
    reviewed_on: date | None = None
    cases: tuple[GoldenCase, ...] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _cases_inherit_the_file_split(cls, data: Any) -> Any:
        """The split is written once at the top of the file; each case receives it."""
        if isinstance(data, dict) and isinstance(data.get("cases"), list):
            split = data.get("split")
            cases = [{"split": split, **c} if isinstance(c, dict) else c for c in data["cases"]]
            return {**data, "cases": cases}
        return data

    @model_validator(mode="after")
    def _no_case_overrides_the_split(self) -> Self:
        mismatched = [case.id for case in self.cases if case.split is not self.split]
        if mismatched:
            raise ValueError(f"cases declare a different split than the file: {mismatched}")
        if (self.reviewed_by is None) != (self.reviewed_on is None):
            raise ValueError("reviewed_by and reviewed_on must be set together")
        return self


@dataclass(frozen=True, slots=True)
class GoldenSet:
    cases: tuple[GoldenCase, ...]
    reviewed: bool = False
    """True only when every split file names a human reviewer."""

    def split(self, split: Split) -> tuple[GoldenCase, ...]:
        return tuple(case for case in self.cases if case.split is split)

    def violations(self, taxonomy: Taxonomy) -> list[str]:
        return [problem for case in self.cases for problem in case.violations(taxonomy)]


def load_golden_set(golden_dir: Path) -> GoldenSet:
    cases: list[GoldenCase] = []
    reviewed = True
    for split, filename in SPLIT_FILES.items():
        path = golden_dir / filename
        golden_file = load_model(GoldenFile, path)
        if golden_file.split is not split:
            raise ConfigError(f"{path}: file declares split {golden_file.split}, expected {split}")
        cases.extend(golden_file.cases)
        reviewed = reviewed and golden_file.reviewed_by is not None
    duplicates = sorted(case_id for case_id, n in Counter(c.id for c in cases).items() if n > 1)
    if duplicates:
        raise ConfigError(f"{golden_dir}: duplicate case ids {duplicates}")
    return GoldenSet(tuple(cases), reviewed=reviewed)
