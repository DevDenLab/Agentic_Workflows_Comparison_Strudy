"""Step 1 — Intake: turn what arrived (an .eml file or a web form post) into an InboundMessage.

Production intake would read IMAP / Microsoft Graph or sit behind a web framework.
The output contract is the same, so nothing downstream would change.
"""

import hashlib
from collections.abc import Iterator
from datetime import datetime
from email import message_from_string, policy
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

from pydantic import AwareDatetime, Field

from triage.clock import Clock
from triage.config import ConfigModel
from triage.contracts import Channel, InboundMessage

UNKNOWN_SENDER = "unknown"


class WebFormSubmission(ConfigModel):
    submission_id: str = Field(min_length=1)
    email: str = Field(min_length=1)
    subject: str
    description: str
    submitted_at: AwareDatetime | None = None


class EmailFileIntake:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def read(self, path: Path) -> InboundMessage:
        return self.from_raw(path.read_bytes().decode("utf-8", errors="replace"))

    def read_directory(self, directory: Path) -> Iterator[InboundMessage]:
        for path in sorted(directory.glob("*.eml")):
            yield self.read(path)

    def from_raw(self, raw: str) -> InboundMessage:
        headers = message_from_string(raw, policy=policy.default)
        return InboundMessage(
            message_id=str(headers.get("Message-ID", "")).strip() or _content_hash(raw),
            channel=Channel.EMAIL,
            received_at=_parse_date(headers.get("Date")) or self._clock.now(),
            sender=parseaddr(str(headers.get("From", "")))[1] or UNKNOWN_SENDER,
            subject=str(headers.get("Subject", "")).strip(),
            raw_body=raw,
        )


class WebFormIntake:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def receive(self, submission: WebFormSubmission) -> InboundMessage:
        return InboundMessage(
            message_id=f"webform:{submission.submission_id}",
            channel=Channel.WEB_FORM,
            received_at=submission.submitted_at or self._clock.now(),
            sender=submission.email,
            subject=submission.subject.strip(),
            raw_body=submission.description,
        )


def _content_hash(raw: str) -> str:
    """Idempotency key for mail with no Message-ID: the same bytes always get the same key."""
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse_date(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(str(value))
    except (TypeError, ValueError):
        return None
    # RFC 5322 "-0000" means "timezone unknown"; parsedate returns a naive datetime for it.
    return parsed if parsed.tzinfo is not None else None
