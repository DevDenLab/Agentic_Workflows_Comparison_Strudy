"""Time as an injected dependency, so tests and benchmark replays control it."""

import time
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Timezone-aware current time."""
        ...

    def monotonic(self) -> float:
        """Seconds from an arbitrary origin. Only differences are meaningful."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        # perf_counter, not time.monotonic: on Windows the latter ticks every ~15.6 ms,
        # which would make every latency measurement a multiple of 15.6 ms.
        return time.perf_counter()


class FixedClock:
    """A clock that only moves when told to."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("FixedClock needs a timezone-aware datetime")
        self._now = start
        self._monotonic = 0.0

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)
        self._monotonic += seconds
