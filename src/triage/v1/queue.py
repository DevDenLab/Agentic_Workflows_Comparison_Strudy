"""Step 2 — Queue & Dedupe.

The queue delivers at least once: a consumer that dies mid-ticket loses its lease and the message
comes back. So the same message can be processed twice, and so can a user's double submit.
The idempotency store is the cheap first defence; the ITSM write's idempotency key is the guarantee.
"""

from dataclasses import dataclass
from typing import Protocol

from pydantic import Field

from triage.clock import Clock
from triage.config import ConfigModel
from triage.contracts import InboundMessage, Outcome
from triage.v1.storage import SqliteDatabase

_SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_messages (
    namespace   TEXT NOT NULL,
    message_id  TEXT NOT NULL,
    outcome     TEXT NOT NULL,
    recorded_at REAL NOT NULL,
    PRIMARY KEY (namespace, message_id)
);
CREATE TABLE IF NOT EXISTS message_queue (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    payload      TEXT NOT NULL,
    enqueued_at  REAL NOT NULL,
    leased_until REAL,
    deliveries   INTEGER NOT NULL DEFAULT 0,
    acked_at     REAL
);
"""


class QueueConfig(ConfigModel):
    lease_seconds: float = Field(gt=0)


class IdempotencyStore(Protocol):
    def seen(self, message_id: str) -> bool: ...

    def record(self, message_id: str, outcome: Outcome) -> None: ...


class SqliteIdempotencyStore:
    """`namespace` isolates independent runs, e.g. each benchmark repetition, in one database."""

    def __init__(self, db: SqliteDatabase, clock: Clock, namespace: str = "default") -> None:
        db.apply_schema(_SCHEMA)
        self._db = db
        self._clock = clock
        self._namespace = namespace

    def seen(self, message_id: str) -> bool:
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT 1 FROM processed_messages WHERE namespace = ? AND message_id = ?",
                (self._namespace, message_id),
            ).fetchone()
        return row is not None

    def record(self, message_id: str, outcome: Outcome) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO processed_messages VALUES (?, ?, ?, ?)",
                (self._namespace, message_id, outcome.value, self._clock.now().timestamp()),
            )


@dataclass(frozen=True, slots=True)
class Delivery:
    delivery_id: int
    message: InboundMessage
    attempt: int
    """1 on first delivery. Higher means the previous consumer's lease expired."""


class SqliteMessageQueue:
    def __init__(self, db: SqliteDatabase, clock: Clock, config: QueueConfig) -> None:
        db.apply_schema(_SCHEMA)
        self._db = db
        self._clock = clock
        self._lease_seconds = config.lease_seconds

    def enqueue(self, message: InboundMessage) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO message_queue (payload, enqueued_at) VALUES (?, ?)",
                (message.model_dump_json(), self._clock.now().timestamp()),
            )

    def lease(self) -> Delivery | None:
        """Take the oldest message nobody holds. The claim is one atomic UPDATE."""
        now = self._clock.now().timestamp()
        with self._db.transaction() as conn:
            row = conn.execute(
                "UPDATE message_queue SET leased_until = ?, deliveries = deliveries + 1 "
                "WHERE id = (SELECT id FROM message_queue WHERE acked_at IS NULL "
                "            AND (leased_until IS NULL OR leased_until <= ?) ORDER BY id LIMIT 1) "
                "RETURNING id, payload, deliveries",
                (now + self._lease_seconds, now),
            ).fetchone()
        if row is None:
            return None
        return Delivery(
            delivery_id=row[0], message=InboundMessage.model_validate_json(row[1]), attempt=row[2]
        )

    def ack(self, delivery: Delivery) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE message_queue SET acked_at = ? WHERE id = ?",
                (self._clock.now().timestamp(), delivery.delivery_id),
            )

    def depth(self) -> int:
        with self._db.transaction() as conn:
            (count,) = conn.execute(
                "SELECT COUNT(*) FROM message_queue WHERE acked_at IS NULL"
            ).fetchone()
        return int(count)
