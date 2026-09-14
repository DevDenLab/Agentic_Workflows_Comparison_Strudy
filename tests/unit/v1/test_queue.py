from datetime import UTC, datetime
from pathlib import Path

import pytest

from triage.clock import FixedClock
from triage.contracts import Channel, InboundMessage, Outcome
from triage.v1.queue import QueueConfig, SqliteIdempotencyStore, SqliteMessageQueue
from triage.v1.storage import SqliteDatabase, StorageConfig

START = datetime(2026, 9, 14, 15, 0, tzinfo=UTC)
LEASE = QueueConfig(lease_seconds=300)


@pytest.fixture
def db(tmp_path: Path) -> SqliteDatabase:
    return SqliteDatabase(tmp_path / "triage.sqlite3", StorageConfig(busy_timeout_seconds=1))


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(START)


def _message(message_id: str) -> InboundMessage:
    return InboundMessage(
        message_id=message_id,
        channel=Channel.WEB_FORM,
        received_at=START,
        sender="liam.chen@contoso.example",
        subject="Printer jam",
        raw_body="Paper jam on 4B",
    )


# --- idempotency ---------------------------------------------------------------


def test_unseen_message_is_not_a_duplicate(db: SqliteDatabase, clock: FixedClock) -> None:
    assert not SqliteIdempotencyStore(db, clock).seen("m-1")


def test_recorded_message_is_a_duplicate(db: SqliteDatabase, clock: FixedClock) -> None:
    store = SqliteIdempotencyStore(db, clock)

    store.record("m-1", Outcome.AUTO_RESOLVED)
    store.record("m-1", Outcome.AUTO_RESOLVED)  # recording twice is harmless

    assert store.seen("m-1")


def test_record_survives_a_restart(db: SqliteDatabase, clock: FixedClock) -> None:
    SqliteIdempotencyStore(db, clock).record("m-1", Outcome.HUMAN_REVIEW)

    assert SqliteIdempotencyStore(db, clock).seen("m-1")


def test_namespaces_are_isolated(db: SqliteDatabase, clock: FixedClock) -> None:
    SqliteIdempotencyStore(db, clock, namespace="run-1").record("m-1", Outcome.AUTO_RESOLVED)

    assert not SqliteIdempotencyStore(db, clock, namespace="run-2").seen("m-1")


# --- queue ---------------------------------------------------------------------


def test_messages_are_delivered_oldest_first(db: SqliteDatabase, clock: FixedClock) -> None:
    queue = SqliteMessageQueue(db, clock, LEASE)
    queue.enqueue(_message("m-1"))
    queue.enqueue(_message("m-2"))

    first, second = queue.lease(), queue.lease()

    assert first is not None
    assert second is not None
    assert (first.message.message_id, second.message.message_id) == ("m-1", "m-2")
    assert queue.lease() is None


def test_leased_message_is_not_given_to_a_second_consumer(
    db: SqliteDatabase, clock: FixedClock
) -> None:
    queue = SqliteMessageQueue(db, clock, LEASE)
    queue.enqueue(_message("m-1"))

    assert queue.lease() is not None
    assert queue.lease() is None


def test_expired_lease_redelivers_the_message(db: SqliteDatabase, clock: FixedClock) -> None:
    """At-least-once: the consumer died without acking, so the message comes back."""
    queue = SqliteMessageQueue(db, clock, LEASE)
    queue.enqueue(_message("m-1"))
    queue.lease()

    clock.advance(301)
    redelivery = queue.lease()

    assert redelivery is not None
    assert redelivery.message.message_id == "m-1"
    assert redelivery.attempt == 2


def test_acked_message_is_never_redelivered(db: SqliteDatabase, clock: FixedClock) -> None:
    queue = SqliteMessageQueue(db, clock, LEASE)
    queue.enqueue(_message("m-1"))
    delivery = queue.lease()
    assert delivery is not None

    queue.ack(delivery)
    clock.advance(10_000)

    assert queue.lease() is None
    assert queue.depth() == 0


def test_depth_counts_unacknowledged_messages(db: SqliteDatabase, clock: FixedClock) -> None:
    queue = SqliteMessageQueue(db, clock, LEASE)
    for i in range(3):
        queue.enqueue(_message(f"m-{i}"))
    queue.lease()

    assert queue.depth() == 3
