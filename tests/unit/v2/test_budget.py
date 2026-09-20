from datetime import UTC, datetime

import pytest

from triage.clock import FixedClock
from triage.v2.budget import BudgetConfig, BudgetExceeded, BudgetGovernor

NOW = datetime(2026, 9, 14, 15, 0, tzinfo=UTC)
CONFIG = BudgetConfig(max_steps=3, max_total_tokens=1000, max_wall_seconds=60)


def test_check_passes_under_budget() -> None:
    BudgetGovernor(CONFIG, FixedClock(NOW)).check()  # does not raise


def test_step_limit_is_enforced() -> None:
    governor = BudgetGovernor(CONFIG, FixedClock(NOW))
    for _ in range(3):
        governor.check()
        governor.record(prompt_tokens=1, completion_tokens=1)

    with pytest.raises(BudgetExceeded, match="max_steps"):
        governor.check()


def test_token_limit_is_enforced() -> None:
    governor = BudgetGovernor(CONFIG, FixedClock(NOW))
    governor.record(prompt_tokens=900, completion_tokens=200)

    with pytest.raises(BudgetExceeded, match="max_total_tokens"):
        governor.check()


def test_wall_clock_limit_is_enforced() -> None:
    clock = FixedClock(NOW)
    governor = BudgetGovernor(CONFIG, clock)
    clock.advance(61)

    with pytest.raises(BudgetExceeded, match="max_wall_seconds"):
        governor.check()


def test_elapsed_seconds_tracks_the_clock() -> None:
    clock = FixedClock(NOW)
    governor = BudgetGovernor(CONFIG, clock)
    clock.advance(12.5)

    assert governor.elapsed_seconds == 12.5
