from collections.abc import Callable

import pytest
from pydantic import ValidationError

from triage.config import LoadedConfig
from triage.v1.cmdb import CmdbContext
from triage.v1.routing_table import RouteCondition, RoutingConfig, RoutingTable
from triage.v1.settings import V1Config

ContextFactory = Callable[..., CmdbContext]


@pytest.fixture(scope="module")
def table(v1_config: V1Config) -> RoutingTable:
    return RoutingTable(v1_config.routing)


def test_default_route(table: RoutingTable, make_context: ContextFactory) -> None:
    decision = table.route(category="printing", rule_id="R060", context=make_context())

    assert decision.group == "desktop_support"
    assert decision.reason == "default route for printing"


def test_rule_id_override(table: RoutingTable, make_context: ContextFactory) -> None:
    decision = table.route(category="access_identity", rule_id="R011", context=make_context())

    assert decision.group == "identity_access"


def test_asset_service_override(table: RoutingTable, make_context: ContextFactory) -> None:
    context = make_context(asset_service="clinical_device_fleet")

    decision = table.route(category="end_user_hardware", rule_id="R070", context=context)

    assert decision.group == "clinical_engineering"


def test_override_needs_every_condition_to_hold(
    table: RoutingTable, make_context: ContextFactory
) -> None:
    context = make_context(asset_service="end_user_computing")

    decision = table.route(category="end_user_hardware", rule_id="R070", context=context)

    assert decision.group == "desktop_support"


def test_llm_decisions_without_a_rule_id_still_route(
    table: RoutingTable, make_context: ContextFactory
) -> None:
    decision = table.route(category="access_identity", rule_id=None, context=make_context())

    assert decision.group == "service_desk_l1"


def test_shipped_routing_matches_taxonomy(v1_config: V1Config, loaded_config: LoadedConfig) -> None:
    assert v1_config.routing.violations(loaded_config.taxonomy) == []


def test_gaps_and_unknown_values_are_reported(loaded_config: LoadedConfig) -> None:
    config = RoutingConfig(
        version="1.0.0", routes={"printing": "helpdesk", "faxing": "desktop_support"}
    )

    violations = config.violations(loaded_config.taxonomy)

    assert "category 'access_identity' has no route" in violations
    assert "route for unknown category 'faxing'" in violations
    assert "unknown assignment group 'helpdesk'" in violations


def test_override_without_conditions_is_rejected() -> None:
    with pytest.raises(ValidationError, match="at least one condition"):
        RouteCondition()
