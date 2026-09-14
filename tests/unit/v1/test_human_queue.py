from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from triage.clock import FixedClock
from triage.contracts import Channel, ExtractedFields, InboundMessage, Ticket, TriageDecision
from triage.v1.human_queue import HumanQueueItem, SqliteHumanQueue
from triage.v1.storage import SqliteDatabase, StorageConfig

NOW = datetime(2026, 9, 14, 15, 0, tzinfo=UTC)
MESSAGE = InboundMessage(
    message_id="m-1",
    channel=Channel.EMAIL,
    received_at=NOW,
    sender="priya.raman@contoso.example",
    subject="Something odd",
    raw_body="The thing on the wall is beeping",
)


def _queue(tmp_path: Path) -> SqliteHumanQueue:
    db = SqliteDatabase(tmp_path / "triage.sqlite3", StorageConfig(busy_timeout_seconds=1))
    return SqliteHumanQueue(db, FixedClock(NOW))


def test_item_with_draft_and_evidence_round_trips(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    correlation_id = uuid4()
    item = HumanQueueItem(
        correlation_id=correlation_id,
        message=MESSAGE,
        reason="confidence below threshold",
        ticket=Ticket(
            correlation_id=correlation_id,
            message_id="m-1",
            channel=Channel.EMAIL,
            received_at=NOW,
            sender=MESSAGE.sender,
            subject=MESSAGE.subject,
            text=MESSAGE.raw_body,
            extracted=ExtractedFields(),
        ),
        draft=TriageDecision(
            category="clinical_devices",
            priority="P2",  # type: ignore[arg-type]
            assignment_group="clinical_engineering",
            draft_response="We have logged your request.",
            confidence=0.55,
        ),
        evidence=("kb:infusion-pump-alarms#2",),
    )

    queue.put(item)

    assert queue.items() == [item]
    assert queue.depth() == 1


def test_message_that_never_became_a_ticket_can_still_be_queued(tmp_path: Path) -> None:
    queue = _queue(tmp_path)

    queue.put(HumanQueueItem(correlation_id=uuid4(), message=MESSAGE, reason="empty body"))

    (stored,) = queue.items()
    assert stored.ticket is None
    assert stored.draft is None
