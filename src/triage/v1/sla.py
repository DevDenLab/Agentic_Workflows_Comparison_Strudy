"""Step 9 — SLA Calculator: when the ticket's resolution target falls due.

Calendar targets run 24x7. Business targets only count business hours on business days, skipping
statutory holidays, in the organisation's timezone. Results are returned in UTC.
"""

from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Self
from zoneinfo import ZoneInfo

import holidays
from pydantic import Field, model_validator

from triage.config import ConfigModel, SemVer
from triage.contracts import Priority


class SlaClock(StrEnum):
    CALENDAR = "calendar"
    BUSINESS = "business"


class Weekday(StrEnum):
    MON = "mon"
    TUE = "tue"
    WED = "wed"
    THU = "thu"
    FRI = "fri"
    SAT = "sat"
    SUN = "sun"


class BusinessHours(ConfigModel):
    start: time
    end: time
    days: tuple[Weekday, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _opens_before_it_closes(self) -> Self:
        if self.start >= self.end:
            raise ValueError("business_hours.start must be before business_hours.end")
        return self


class HolidayCalendar(ConfigModel):
    country: str = Field(min_length=2)
    subdivision: str | None = None


class SlaTarget(ConfigModel):
    hours: float = Field(gt=0)
    clock: SlaClock


class SlaConfig(ConfigModel):
    """config/sla.yaml"""

    version: SemVer
    business_hours: BusinessHours
    holidays: HolidayCalendar
    targets: dict[Priority, SlaTarget]

    @model_validator(mode="after")
    def _every_priority_has_a_target(self) -> Self:
        missing = [p.value for p in Priority if p not in self.targets]
        if missing:
            raise ValueError(f"no SLA target for {missing}")
        return self


class SlaCalculator:
    def __init__(self, config: SlaConfig, timezone: str) -> None:
        self._tz = ZoneInfo(timezone)
        self._open = config.business_hours.start
        self._close = config.business_hours.end
        self._days = frozenset(list(Weekday).index(day) for day in config.business_hours.days)
        self._targets = config.targets
        self._holidays = holidays.country_holidays(
            config.holidays.country, subdiv=config.holidays.subdivision
        )

    def due_at(self, received_at: datetime, priority: Priority) -> datetime:
        target = self._targets[priority]
        duration = timedelta(hours=target.hours)
        if target.clock is SlaClock.CALENDAR:
            return (received_at + duration).astimezone(UTC)
        return self._add_business_time(received_at, duration).astimezone(UTC)

    def is_business_day(self, day: date) -> bool:
        return day.weekday() in self._days and day not in self._holidays

    def is_business_time(self, moment: datetime) -> bool:
        local = moment.astimezone(self._tz)
        return self.is_business_day(local.date()) and self._open <= local.time() < self._close

    def _add_business_time(self, start: datetime, remaining: timedelta) -> datetime:
        # Business hours never span a DST change (those happen at 02:00), so wall-clock arithmetic
        # within a single business day is exact.
        cursor = start.astimezone(self._tz)
        day = cursor.date()
        while True:
            if self.is_business_day(day):
                opens = datetime.combine(day, self._open, self._tz)
                closes = datetime.combine(day, self._close, self._tz)
                begin = max(cursor, opens)
                if begin < closes:
                    available = closes - begin
                    if remaining <= available:
                        return begin + remaining
                    remaining -= available
            day += timedelta(days=1)
            cursor = datetime.combine(day, time.min, self._tz)
