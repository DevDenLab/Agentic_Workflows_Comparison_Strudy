"""Step 10 — Routing Table: category -> assignment group, with CMDB-aware overrides.

Overrides are checked first, in file order. The first whose conditions all hold wins.
"""

from dataclasses import dataclass
from typing import Self

from pydantic import Field, model_validator

from triage.config import ConfigModel, SemVer
from triage.contracts import Taxonomy
from triage.v1.cmdb import CmdbContext


class RouteCondition(ConfigModel):
    category: str | None = None
    rule_id: str | None = None
    asset_service: str | None = None

    @model_validator(mode="after")
    def _has_a_condition(self) -> Self:
        if self.category is None and self.rule_id is None and self.asset_service is None:
            raise ValueError("an override needs at least one condition")
        return self

    def holds(self, *, category: str, rule_id: str | None, context: CmdbContext) -> bool:
        asset_service = context.asset.service.service_id if context.asset else None
        return (
            (self.category is None or self.category == category)
            and (self.rule_id is None or self.rule_id == rule_id)
            and (self.asset_service is None or self.asset_service == asset_service)
        )


class RouteOverride(ConfigModel):
    when: RouteCondition
    group: str
    reason: str = Field(min_length=1)


class RoutingConfig(ConfigModel):
    """config/routing.yaml"""

    version: SemVer
    routes: dict[str, str]
    overrides: tuple[RouteOverride, ...] = ()

    def violations(self, taxonomy: Taxonomy) -> list[str]:
        routed = set(self.routes)
        groups = {*self.routes.values(), *(override.group for override in self.overrides)}
        override_categories = {o.when.category for o in self.overrides if o.when.category}
        return [
            *(f"category {c!r} has no route" for c in sorted(taxonomy.category_ids - routed)),
            *(f"route for unknown category {c!r}" for c in sorted(routed - taxonomy.category_ids)),
            *(f"unknown assignment group {g!r}" for g in sorted(groups - taxonomy.group_ids)),
            *(
                f"override for unknown category {c!r}"
                for c in sorted(override_categories - taxonomy.category_ids)
            ),
        ]


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    group: str
    reason: str


class RoutingTable:
    def __init__(self, config: RoutingConfig) -> None:
        self._routes = config.routes
        self._overrides = config.overrides

    def route(self, *, category: str, rule_id: str | None, context: CmdbContext) -> RoutingDecision:
        for override in self._overrides:
            if override.when.holds(category=category, rule_id=rule_id, context=context):
                return RoutingDecision(override.group, override.reason)
        return RoutingDecision(self._routes[category], f"default route for {category}")
