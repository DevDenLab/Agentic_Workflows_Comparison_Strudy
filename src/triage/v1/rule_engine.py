"""Step 7 — Rule Engine: ordered keyword rules from config/rules.yaml. The first match wins.

This is all of v1's "intelligence", and its limit: it only knows phrasings someone wrote down.
v2 exposes this same engine to the agent as the `apply_rules` tool.
"""

import re
from dataclasses import dataclass

from pydantic import Field, field_validator

from triage.config import ConfigModel, SemVer
from triage.contracts import Taxonomy
from triage.v1.phrases import Phrase, compile_phrase
from triage.v1.priority_matrix import Level


class Rule(ConfigModel):
    id: str = Field(pattern=r"^R\d{3}$")
    description: str = Field(min_length=1)
    category: str
    urgency: Level
    any_of: tuple[Phrase, ...] = Field(min_length=1)
    none_of: tuple[Phrase, ...] = ()


class RuleSet(ConfigModel):
    """config/rules.yaml"""

    version: SemVer
    rules: tuple[Rule, ...] = Field(min_length=1)

    @field_validator("rules")
    @classmethod
    def _ids_are_unique(cls, rules: tuple[Rule, ...]) -> tuple[Rule, ...]:
        ids = [rule.id for rule in rules]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate rule ids: {duplicates}")
        return rules

    def violations(self, taxonomy: Taxonomy) -> list[str]:
        return [
            f"rule {rule.id}: category {rule.category!r} is not in the taxonomy"
            for rule in self.rules
            if rule.category not in taxonomy.category_ids
        ]


@dataclass(frozen=True, slots=True)
class RuleMatch:
    rule_id: str
    category: str
    urgency: Level
    matched_phrase: str


@dataclass(frozen=True, slots=True)
class _CompiledRule:
    rule: Rule
    any_of: tuple[tuple[str, re.Pattern[str]], ...]
    none_of: tuple[re.Pattern[str], ...]

    def match(self, haystack: str) -> RuleMatch | None:
        if any(pattern.search(haystack) for pattern in self.none_of):
            return None
        for phrase, pattern in self.any_of:
            if pattern.search(haystack):
                return RuleMatch(self.rule.id, self.rule.category, self.rule.urgency, phrase)
        return None


class RuleEngine:
    def __init__(self, rules: RuleSet) -> None:
        self.version = rules.version
        self._rules = tuple(
            _CompiledRule(
                rule=rule,
                any_of=tuple((phrase, compile_phrase(phrase)) for phrase in rule.any_of),
                none_of=tuple(compile_phrase(phrase) for phrase in rule.none_of),
            )
            for rule in rules.rules
        )

    def match(self, subject: str, text: str) -> RuleMatch | None:
        haystack = f"{subject}\n{text}"
        for rule in self._rules:
            hit = rule.match(haystack)
            if hit is not None:
                return hit
        return None
