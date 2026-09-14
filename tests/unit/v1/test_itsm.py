from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from triage.clock import FixedClock
from triage.contracts import TriageDecision
from triage.v1.itsm import (
    FaultInjectionConfig,
    FaultInjector,
    ItsmClient,
    ItsmTicketRef,
    ItsmTicketRequest,
    ItsmWriter,
    PermanentItsmError,
    RetryPolicy,
    SqliteDeadLetterQueue,
    SqliteItsm,
    TransientItsmError,
    idempotency_key,
)
from triage.v1.storage import SqliteDatabase, StorageConfig

NO_FAULTS = FaultInjectionConfig(failure_rate=0.0, seed=1)
POLICY = RetryPolicy(
    max_attempts=3, initial_backoff_seconds=1, max_backoff_seconds=4, jitter_seconds=0
)


class ScriptedClient:
    """Raises the scripted errors in order, then delegates to the real stand-in ITSM.

    `lose_response=True` makes each scripted error happen AFTER the ticket was created,
    i.e. the ITSM did the work but the reply never arrived.
    """

    def __init__(
        self, inner: ItsmClient, errors: list[Exception], *, lose_response: bool = False
    ) -> None:
        self._inner = inner
        self._errors = errors
        self._lose_response = lose_response

    def create_ticket(self, request: ItsmTicketRequest) -> ItsmTicketRef:
        if self._errors:
            if self._lose_response:
                self._inner.create_ticket(request)
            raise self._errors.pop(0)
        return self._inner.create_ticket(request)


@pytest.fixture
def db(tmp_path: Path) -> SqliteDatabase:
    return SqliteDatabase(tmp_path / "itsm.sqlite3", StorageConfig(busy_timeout_seconds=1))


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 9, 14, 15, 0, tzinfo=UTC))


@pytest.fixture
def itsm(db: SqliteDatabase, clock: FixedClock) -> SqliteItsm:
    return SqliteItsm(db, clock, FaultInjector(NO_FAULTS))


@pytest.fixture
def dlq(db: SqliteDatabase, clock: FixedClock) -> SqliteDeadLetterQueue:
    return SqliteDeadLetterQueue(db, clock)


def _request(message_id: str = "m-1") -> ItsmTicketRequest:
    return ItsmTicketRequest(
        idempotency_key=idempotency_key(message_id),
        correlation_id=uuid4(),
        requester="liam.chen@contoso.example",
        subject="Printer jam",
        description="Paper jam on 4B",
        decision=TriageDecision(
            category="printing",
            priority="P4",  # type: ignore[arg-type]
            assignment_group="desktop_support",
            draft_response="We have logged your request.",
            confidence=1.0,
        ),
    )


def _writer(client: ItsmClient, dlq: SqliteDeadLetterQueue, sleeps: list[float]) -> ItsmWriter:
    return ItsmWriter(client, dlq, POLICY, sleep=sleeps.append)


def test_same_idempotency_key_returns_the_existing_ticket(itsm: SqliteItsm) -> None:
    first = itsm.create_ticket(_request())
    second = itsm.create_ticket(_request())

    assert first.created
    assert not second.created
    assert first.number == second.number
    assert itsm.count() == 1


def test_different_messages_get_different_tickets(itsm: SqliteItsm) -> None:
    assert itsm.create_ticket(_request("m-1")).number != itsm.create_ticket(_request("m-2")).number


def test_transient_failures_are_retried_with_exponential_backoff(
    itsm: SqliteItsm, dlq: SqliteDeadLetterQueue
) -> None:
    sleeps: list[float] = []
    client = ScriptedClient(itsm, [TransientItsmError("timeout"), TransientItsmError("503")])

    outcome = _writer(client, dlq, sleeps).write(_request())

    assert outcome.ref is not None
    assert outcome.attempts == 3
    assert sleeps == [1.0, 2.0]
    assert dlq.depth() == 0


def test_backoff_is_capped(itsm: SqliteItsm, dlq: SqliteDeadLetterQueue) -> None:
    sleeps: list[float] = []
    policy = POLICY.model_copy(update={"max_attempts": 5, "max_backoff_seconds": 3})
    client = ScriptedClient(itsm, [TransientItsmError("503") for _ in range(4)])

    ItsmWriter(client, dlq, policy, sleep=sleeps.append).write(_request())

    assert sleeps == [1.0, 2.0, 3.0, 3.0]


def test_exhausted_retries_dead_letter_the_request(
    itsm: SqliteItsm, dlq: SqliteDeadLetterQueue
) -> None:
    client = ScriptedClient(itsm, [TransientItsmError("ITSM unavailable") for _ in range(3)])

    outcome = _writer(client, dlq, []).write(_request())

    assert outcome.dead_lettered
    assert outcome.attempts == 3
    assert outcome.error == "ITSM unavailable"
    assert dlq.depth() == 1
    assert itsm.count() == 0


def test_permanent_errors_are_not_retried(itsm: SqliteItsm, dlq: SqliteDeadLetterQueue) -> None:
    sleeps: list[float] = []
    client = ScriptedClient(itsm, [PermanentItsmError("400: unknown assignment group")])

    outcome = _writer(client, dlq, sleeps).write(_request())

    assert outcome.dead_lettered
    assert outcome.attempts == 1
    assert sleeps == []


def test_retry_after_a_lost_response_does_not_create_a_duplicate(
    itsm: SqliteItsm, dlq: SqliteDeadLetterQueue
) -> None:
    """The case idempotency keys exist for: the first call worked, but its reply was lost."""
    client = ScriptedClient(itsm, [TransientItsmError("read timeout")], lose_response=True)

    outcome = _writer(client, dlq, []).write(_request())

    assert outcome.ref is not None
    assert not outcome.ref.created
    assert itsm.count() == 1


def test_fault_injection_is_reproducible() -> None:
    def pattern(injector: FaultInjector) -> list[bool]:
        results = []
        for _ in range(20):
            try:
                injector.maybe_fail()
                results.append(True)
            except TransientItsmError:
                results.append(False)
        return results

    config = FaultInjectionConfig(failure_rate=0.5, seed=42)

    assert pattern(FaultInjector(config)) == pattern(FaultInjector(config))
    assert not all(pattern(FaultInjector(config)))
    assert all(pattern(FaultInjector(NO_FAULTS)))


def test_idempotency_key_is_stable_per_message() -> None:
    assert idempotency_key("<a@contoso.example>") == idempotency_key("<a@contoso.example>")
    assert idempotency_key("<a@contoso.example>") != idempotency_key("<b@contoso.example>")
