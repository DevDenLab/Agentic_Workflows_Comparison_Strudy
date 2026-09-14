"""Step 12 — ITSM Write: create the ticket exactly once, even when the ITSM is flaky.

1. Idempotency: every request carries a key derived from the message id. A retry, or a redelivered
   message, returns the existing ticket instead of creating a second one.
2. Retries: transient failures are retried with exponential backoff and jitter, limits from config.
3. Dead letter: a request that still fails is parked with its error for replay. Never dropped.
"""

import hashlib
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from triage.clock import Clock
from triage.config import ConfigModel
from triage.contracts import TriageDecision
from triage.v1.storage import SqliteDatabase

_ITSM_SCHEMA = """
CREATE TABLE IF NOT EXISTS itsm_tickets (
    number          INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT NOT NULL UNIQUE,
    payload         TEXT NOT NULL,
    created_at      REAL NOT NULL
);
"""

_DLQ_SCHEMA = """
CREATE TABLE IF NOT EXISTS dead_letters (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT NOT NULL,
    payload         TEXT NOT NULL,
    error           TEXT NOT NULL,
    attempts        INTEGER NOT NULL,
    failed_at       REAL NOT NULL
);
"""


class RetryPolicy(ConfigModel):
    max_attempts: int = Field(ge=1)
    initial_backoff_seconds: float = Field(gt=0)
    max_backoff_seconds: float = Field(gt=0)
    jitter_seconds: float = Field(ge=0)


class FaultInjectionConfig(ConfigModel):
    failure_rate: float = Field(ge=0, le=1)
    seed: int


class ItsmConfig(ConfigModel):
    retry: RetryPolicy
    fault_injection: FaultInjectionConfig


class TransientItsmError(Exception):
    """Timeout or 5xx: worth retrying."""


class PermanentItsmError(Exception):
    """The ITSM rejected the request (4xx): retrying cannot help."""


def idempotency_key(message_id: str) -> str:
    return "triage-" + hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:32]


class ItsmTicketRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    idempotency_key: str = Field(min_length=1)
    correlation_id: UUID
    requester: str
    subject: str
    description: str
    decision: TriageDecision


@dataclass(frozen=True, slots=True)
class ItsmTicketRef:
    number: str
    created: bool
    """False when the idempotency key already existed and the original ticket was returned."""


class ItsmClient(Protocol):
    def create_ticket(self, request: ItsmTicketRequest) -> ItsmTicketRef: ...


class FaultInjector:
    """Makes the stand-in ITSM fail on purpose, reproducibly, to exercise retries and the DLQ."""

    def __init__(self, config: FaultInjectionConfig) -> None:
        self._rate = config.failure_rate
        self._rng = random.Random(config.seed)  # noqa: S311 - test fault injection, not security

    def maybe_fail(self) -> None:
        if self._rate and self._rng.random() < self._rate:
            raise TransientItsmError("injected fault: ITSM unavailable")


class SqliteItsm:
    """Stand-in for a real ITSM such as ServiceNow. Same contract, local storage."""

    def __init__(self, db: SqliteDatabase, clock: Clock, faults: FaultInjector) -> None:
        db.apply_schema(_ITSM_SCHEMA)
        self._db = db
        self._clock = clock
        self._faults = faults

    def create_ticket(self, request: ItsmTicketRequest) -> ItsmTicketRef:
        self._faults.maybe_fail()
        with self._db.transaction() as conn:
            inserted = conn.execute(
                "INSERT INTO itsm_tickets (idempotency_key, payload, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT (idempotency_key) DO NOTHING",
                (request.idempotency_key, request.model_dump_json(), self._clock.now().timestamp()),
            ).rowcount
            (number,) = conn.execute(
                "SELECT number FROM itsm_tickets WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
        return ItsmTicketRef(number=f"INC{number:07d}", created=inserted == 1)

    def count(self) -> int:
        with self._db.transaction() as conn:
            (count,) = conn.execute("SELECT COUNT(*) FROM itsm_tickets").fetchone()
        return int(count)


class DeadLetterQueue(Protocol):
    def put(self, request: ItsmTicketRequest, *, error: str, attempts: int) -> None: ...

    def depth(self) -> int: ...


class SqliteDeadLetterQueue:
    def __init__(self, db: SqliteDatabase, clock: Clock) -> None:
        db.apply_schema(_DLQ_SCHEMA)
        self._db = db
        self._clock = clock

    def put(self, request: ItsmTicketRequest, *, error: str, attempts: int) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO dead_letters (idempotency_key, payload, error, attempts, failed_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    request.idempotency_key,
                    request.model_dump_json(),
                    error,
                    attempts,
                    self._clock.now().timestamp(),
                ),
            )

    def depth(self) -> int:
        with self._db.transaction() as conn:
            (count,) = conn.execute("SELECT COUNT(*) FROM dead_letters").fetchone()
        return int(count)


@dataclass(frozen=True, slots=True)
class WriteOutcome:
    ref: ItsmTicketRef | None
    attempts: int
    error: str | None = None

    @property
    def dead_lettered(self) -> bool:
        return self.ref is None


class ItsmWriter:
    def __init__(
        self,
        client: ItsmClient,
        dead_letters: DeadLetterQueue,
        policy: RetryPolicy,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._dead_letters = dead_letters
        self._policy = policy
        self._sleep = sleep

    def write(self, request: ItsmTicketRequest) -> WriteOutcome:
        retrying = Retrying(
            stop=stop_after_attempt(self._policy.max_attempts),
            wait=wait_exponential_jitter(
                initial=self._policy.initial_backoff_seconds,
                max=self._policy.max_backoff_seconds,
                jitter=self._policy.jitter_seconds,
            ),
            retry=retry_if_exception_type(TransientItsmError),
            sleep=self._sleep,
            reraise=True,
        )
        attempts = 0
        ref: ItsmTicketRef | None = None
        try:
            for attempt in retrying:
                with attempt:
                    attempts = attempt.retry_state.attempt_number
                    ref = self._client.create_ticket(request)
        except (TransientItsmError, PermanentItsmError) as exc:
            self._dead_letters.put(request, error=str(exc), attempts=attempts)
            return WriteOutcome(ref=None, attempts=attempts, error=str(exc))
        return WriteOutcome(ref=ref, attempts=attempts)
