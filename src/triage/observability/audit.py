"""Audit trail: each decision step becomes a typed event on the result and a structured log line.

The events answer "why did this ticket get this decision?" without re-running anything.
"""

from pydantic import JsonValue

from triage.clock import Clock
from triage.contracts import AuditEvent
from triage.observability.logging import get_logger


class AuditTrail:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._events: list[AuditEvent] = []
        self._log = get_logger("audit")

    def add(self, component: str, event: str, **detail: JsonValue) -> None:
        self._events.append(
            AuditEvent(at=self._clock.now(), component=component, event=event, detail=detail)
        )
        self._log.info(event, step=component, **detail)

    @property
    def events(self) -> tuple[AuditEvent, ...]:
        return tuple(self._events)
