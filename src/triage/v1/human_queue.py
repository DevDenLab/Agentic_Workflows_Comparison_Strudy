"""Human Triage Queue: tickets the automation will not decide on its own.

v1 puts the raw ticket and a reason here. v2 uses the same queue, adding its draft decision and
evidence, so the human starts from a proposal instead of a blank ticket.
"""

from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from triage.clock import Clock
from triage.contracts import InboundMessage, Ticket, TriageDecision
from triage.v1.storage import SqliteDatabase

_SCHEMA = """
CREATE TABLE IF NOT EXISTS human_queue (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    correlation_id TEXT NOT NULL,
    message_id     TEXT NOT NULL,
    reason         TEXT NOT NULL,
    payload        TEXT NOT NULL,
    queued_at      REAL NOT NULL
);
"""


class HumanQueueItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    correlation_id: UUID
    message: InboundMessage
    reason: str = Field(min_length=1)
    ticket: Ticket | None = None
    """None when the message could not be parsed into a valid ticket."""
    draft: TriageDecision | None = None
    evidence: tuple[str, ...] = ()


class HumanQueue(Protocol):
    def put(self, item: HumanQueueItem) -> None: ...

    def depth(self) -> int: ...


class SqliteHumanQueue:
    def __init__(self, db: SqliteDatabase, clock: Clock) -> None:
        db.apply_schema(_SCHEMA)
        self._db = db
        self._clock = clock

    def put(self, item: HumanQueueItem) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO human_queue (correlation_id, message_id, reason, payload, queued_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    str(item.correlation_id),
                    item.message.message_id,
                    item.reason,
                    item.model_dump_json(),
                    self._clock.now().timestamp(),
                ),
            )

    def depth(self) -> int:
        with self._db.transaction() as conn:
            (count,) = conn.execute("SELECT COUNT(*) FROM human_queue").fetchone()
        return int(count)

    def items(self) -> list[HumanQueueItem]:
        with self._db.transaction() as conn:
            rows = conn.execute("SELECT payload FROM human_queue ORDER BY id").fetchall()
        return [HumanQueueItem.model_validate_json(payload) for (payload,) in rows]
