"""Input side of the contract: what intake received, and what the parser hands on."""

from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, Field

from triage.contracts._base import ContractModel, NonEmptyStr


class Channel(StrEnum):
    EMAIL = "email"
    WEB_FORM = "web_form"


class InboundMessage(ContractModel):
    """Exactly what intake received. Nothing parsed yet.

    `message_id` is the idempotency key: the email Message-ID header, or the form submission id.
    """

    message_id: NonEmptyStr
    channel: Channel
    received_at: AwareDatetime
    sender: NonEmptyStr
    subject: str
    raw_body: str = Field(
        description="Full RFC 822 source for email; submitted text for web forms."
    )


class ExtractedFields(ContractModel):
    employee_ids: tuple[str, ...] = ()
    asset_tags: tuple[str, ...] = ()
    error_codes: tuple[str, ...] = ()


class Ticket(ContractModel):
    """A parsed, validated ticket. The decision layer (rules or agent) only ever sees this."""

    correlation_id: UUID
    message_id: NonEmptyStr
    channel: Channel
    received_at: AwareDatetime
    sender: NonEmptyStr
    subject: str
    text: NonEmptyStr = Field(description="Body after MIME, signature and quoted-reply stripping.")
    extracted: ExtractedFields
