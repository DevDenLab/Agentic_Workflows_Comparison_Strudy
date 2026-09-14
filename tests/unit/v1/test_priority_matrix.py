from collections.abc import Callable

import pytest
from pydantic import ValidationError

from triage.contracts import Priority
from triage.v1.cmdb import CmdbContext, Criticality
from triage.v1.priority_matrix import Level, PriorityMatrix, PriorityMatrixConfig
from triage.v1.settings import V1Config

ContextFactory = Callable[..., CmdbContext]
_ORDER = [Level.LOW, Level.MEDIUM, Level.HIGH]


@pytest.fixture(scope="module")
def matrix(v1_config: V1Config) -> PriorityMatrix:
    return PriorityMatrix(v1_config.priority)


def test_one_non_clinical_user_is_low_impact(
    matrix: PriorityMatrix, make_context: ContextFactory
) -> None:
    result = matrix.assess(
        urgency=Level.MEDIUM, context=make_context(clinical=False), subject="", text="laptop slow"
    )

    assert (result.impact, result.priority) == (Level.LOW, Priority.P4)
    assert result.impact_reasons == ("base impact",)


def test_clinical_department_raises_impact(
    matrix: PriorityMatrix, make_context: ContextFactory
) -> None:
    result = matrix.assess(
        urgency=Level.HIGH, context=make_context(clinical=True), subject="", text="EMR frozen"
    )

    assert (result.impact, result.priority) == (Level.MEDIUM, Priority.P2)


def test_high_criticality_asset_raises_impact(
    matrix: PriorityMatrix, make_context: ContextFactory
) -> None:
    context = make_context(
        asset_service="clinical_device_fleet", asset_criticality=Criticality.HIGH
    )

    result = matrix.assess(urgency=Level.HIGH, context=context, subject="", text="cart dead")

    assert result.impact is Level.MEDIUM
    assert "high-criticality service clinical_device_fleet" in result.impact_reasons[0]


def test_widespread_phrase_gives_high_impact(
    matrix: PriorityMatrix, make_context: ContextFactory
) -> None:
    result = matrix.assess(
        urgency=Level.HIGH,
        context=make_context(clinical=True),
        subject="",
        text="The whole unit can't chart",
    )

    assert (result.impact, result.priority) == (Level.HIGH, Priority.P1)
    assert result.impact_reasons == ("ticket says 'whole unit'",)


def test_every_signal_at_the_winning_level_is_a_reason(
    matrix: PriorityMatrix, make_context: ContextFactory
) -> None:
    context = make_context(
        clinical=True, asset_service="clinical_device_fleet", asset_criticality=Criticality.HIGH
    )

    result = matrix.assess(urgency=Level.LOW, context=context, subject="", text="scanner")

    assert len(result.impact_reasons) == 2


def test_shipped_matrix_never_lowers_priority_as_impact_or_urgency_rise(
    v1_config: V1Config,
) -> None:
    cells = v1_config.priority.matrix

    def rank(p: Priority) -> int:
        return -int(p.value[1])  # P1 is the most urgent

    for i, impact in enumerate(_ORDER):
        for j, urgency in enumerate(_ORDER):
            if i + 1 < len(_ORDER):
                assert rank(cells[_ORDER[i + 1]][urgency]) >= rank(cells[impact][urgency])
            if j + 1 < len(_ORDER):
                assert rank(cells[impact][_ORDER[j + 1]]) >= rank(cells[impact][urgency])


def test_incomplete_matrix_is_rejected(v1_config: V1Config) -> None:
    data = v1_config.priority.model_dump(mode="json")
    del data["matrix"]["low"]

    with pytest.raises(ValidationError, match="missing impact/urgency cells"):
        PriorityMatrixConfig.model_validate(data)
