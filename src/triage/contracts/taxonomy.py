from pydantic import Field, field_validator

from triage.contracts._base import ContractModel, NonEmptyStr, TaxonomyId
from triage.contracts.decision import TriageDecision


class TaxonomyEntry(ContractModel):
    id: TaxonomyId
    description: NonEmptyStr


class Taxonomy(ContractModel):
    """The allow-list loaded from config/taxonomy.yaml."""

    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    categories: tuple[TaxonomyEntry, ...] = Field(min_length=1)
    assignment_groups: tuple[TaxonomyEntry, ...] = Field(min_length=1)

    @field_validator("categories", "assignment_groups")
    @classmethod
    def _ids_are_unique(cls, entries: tuple[TaxonomyEntry, ...]) -> tuple[TaxonomyEntry, ...]:
        ids = [entry.id for entry in entries]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate ids: {duplicates}")
        return entries

    @property
    def category_ids(self) -> frozenset[str]:
        return frozenset(entry.id for entry in self.categories)

    @property
    def group_ids(self) -> frozenset[str]:
        return frozenset(entry.id for entry in self.assignment_groups)

    def violations(self, decision: TriageDecision) -> list[str]:
        """Return one message per disallowed value; empty means the decision is allowed.

        Messages list the allowed values, so they can go straight back to a model as a repair hint.
        """
        problems: list[str] = []
        if decision.category not in self.category_ids:
            problems.append(
                f"category {decision.category!r} is not allowed; "
                f"allowed: {sorted(self.category_ids)}"
            )
        if decision.assignment_group not in self.group_ids:
            problems.append(
                f"assignment_group {decision.assignment_group!r} is not allowed; "
                f"allowed: {sorted(self.group_ids)}"
            )
        return problems
