from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from triage.config import LoadedConfig
from triage.contracts import Priority
from triage.v1.settings import V1Config
from triage.v1.sla import SlaCalculator, SlaConfig

EDMONTON = ZoneInfo("America/Edmonton")
QUARTER = timedelta(minutes=15)


@pytest.fixture(scope="module")
def sla(v1_config: V1Config, loaded_config: LoadedConfig) -> SlaCalculator:
    return SlaCalculator(v1_config.sla, loaded_config.app.timezone)


def _local(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=EDMONTON)


def test_p1_runs_on_the_calendar_clock(sla: SlaCalculator) -> None:
    saturday_night = _local(2026, 9, 19, 22, 0)

    assert sla.due_at(saturday_night, Priority.P1) == _local(2026, 9, 20, 2, 0)


def test_business_clock_carries_over_to_the_next_day(sla: SlaCalculator) -> None:
    monday_4pm = _local(2026, 9, 14, 16, 0)

    assert sla.due_at(monday_4pm, Priority.P2) == _local(2026, 9, 15, 15, 0)


def test_weekend_and_evening_accrue_nothing(sla: SlaCalculator) -> None:
    friday_6pm = _local(2026, 9, 18, 18, 0)

    # 24 business hours from Monday 08:00 = Mon 9h + Tue 9h + Wed 6h
    assert sla.due_at(friday_6pm, Priority.P3) == _local(2026, 9, 23, 14, 0)


def test_before_opening_starts_at_opening(sla: SlaCalculator) -> None:
    assert sla.due_at(_local(2026, 9, 14, 6, 0), Priority.P2) == _local(2026, 9, 14, 16, 0)


def test_statutory_holidays_are_skipped(sla: SlaCalculator) -> None:
    day_before_canada_day = _local(2026, 6, 30, 16, 0)

    assert sla.due_at(day_before_canada_day, Priority.P2) == _local(2026, 7, 2, 15, 0)


def test_result_is_utc_and_correct_across_a_dst_change(sla: SlaCalculator) -> None:
    # Clocks went back on Sunday 2 Nov 2025. (tzdata 2026.4 has Alberta on UTC-6 year-round
    # from March 2026, so the 2025 change is the last one to test against.)
    friday_before_dst_ends = _local(2025, 10, 31, 16, 0)

    due = sla.due_at(friday_before_dst_ends, Priority.P2)

    assert due.tzinfo is UTC
    assert due == _local(2025, 11, 3, 15, 0)
    assert friday_before_dst_ends.utcoffset() == timedelta(hours=-6)
    assert due.astimezone(EDMONTON).utcoffset() == timedelta(hours=-7)


@settings(max_examples=60, deadline=None)
@given(
    quarter_hours=st.integers(min_value=0, max_value=4 * 24 * 365 * 2),
    priority=st.sampled_from([Priority.P2, Priority.P3, Priority.P4]),
)
def test_business_time_between_receipt_and_due_equals_the_target(
    v1_config: V1Config, loaded_config: LoadedConfig, quarter_hours: int, priority: Priority
) -> None:
    """Checks the arithmetic against a brute-force count of business quarter-hours."""
    sla = SlaCalculator(v1_config.sla, loaded_config.app.timezone)
    received = datetime(2026, 1, 1, tzinfo=UTC) + quarter_hours * QUARTER

    due = sla.due_at(received, priority)

    counted, cursor = 0, received
    while cursor < due:
        counted += sla.is_business_time(cursor)
        cursor += QUARTER
    assert counted == v1_config.sla.targets[priority].hours * 4
    assert sla.is_business_time(due - QUARTER)


def test_missing_priority_target_is_rejected(v1_config: V1Config) -> None:
    data = v1_config.sla.model_dump(mode="json")
    del data["targets"]["P4"]

    with pytest.raises(ValidationError, match="no SLA target"):
        SlaConfig.model_validate(data)


def test_business_hours_must_open_before_closing(v1_config: V1Config) -> None:
    data = v1_config.sla.model_dump(mode="json")
    data["business_hours"]["end"] = "07:00:00"

    with pytest.raises(ValidationError, match="must be before"):
        SlaConfig.model_validate(data)
