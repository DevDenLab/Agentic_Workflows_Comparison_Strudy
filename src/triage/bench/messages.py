"""Turns a golden case into the InboundMessage a real intake would have produced.

Email cases become genuine RFC 822 messages, so each pipeline's own parser does the MIME work.
"""

from datetime import datetime
from email.message import EmailMessage
from email.utils import format_datetime

from triage.bench.golden import GoldenCase
from triage.contracts import Channel, InboundMessage


def to_message(
    case: GoldenCase, *, received_at: datetime, service_desk_address: str
) -> InboundMessage:
    if case.input.channel is Channel.WEB_FORM:
        return InboundMessage(
            message_id=f"webform:golden-{case.id}",
            channel=Channel.WEB_FORM,
            received_at=received_at,
            sender=case.input.sender,
            subject=case.input.subject,
            raw_body=case.input.body,
        )

    message_id = f"<golden-{case.id.lower()}@bench.contoso.example>"
    email = EmailMessage()
    email["Message-ID"] = message_id
    email["Date"] = format_datetime(received_at)
    email["From"] = case.input.sender
    email["To"] = service_desk_address
    email["Subject"] = case.input.subject
    email.set_content(case.input.body)
    return InboundMessage(
        message_id=message_id,
        channel=Channel.EMAIL,
        received_at=received_at,
        sender=case.input.sender,
        subject=case.input.subject,
        raw_body=email.as_string(),
    )
