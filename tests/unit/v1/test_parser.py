from datetime import UTC, datetime
from email.message import EmailMessage

import pytest

from triage.contracts import Channel, InboundMessage
from triage.v1.parser import Parser, html_to_text
from triage.v1.settings import V1Config


@pytest.fixture(scope="module")
def parser(v1_config: V1Config) -> Parser:
    return Parser(v1_config.parsing.parser)


def _message(raw_body: str, channel: Channel = Channel.EMAIL) -> InboundMessage:
    return InboundMessage(
        message_id="m-1",
        channel=channel,
        received_at=datetime(2026, 9, 14, 9, 0, tzinfo=UTC),
        sender="dana.nurse@contoso.example",
        subject="subject",
        raw_body=raw_body,
    )


def _email(plain: str | None = None, html: str | None = None) -> str:
    email = EmailMessage()
    email["Subject"] = "subject"
    if plain is not None:
        email.set_content(plain)
    if html is not None:
        if plain is None:
            email.set_content(html, subtype="html")
        else:
            email.add_alternative(html, subtype="html")
    return email.as_string()


def test_plain_email_body_without_headers(parser: Parser) -> None:
    assert parser.parse(_message(_email(plain="Printer on 3 West is offline."))) == (
        "Printer on 3 West is offline."
    )


def test_multipart_prefers_plain_text(parser: Parser) -> None:
    raw = _email(plain="plain version", html="<p>html version</p>")

    assert parser.parse(_message(raw)) == "plain version"


def test_html_only_email_is_converted_to_text(parser: Parser) -> None:
    raw = _email(html="<html><style>p{color:red}</style><p>Printer&nbsp;jam</p><p>Unit 4B</p>")

    assert parser.parse(_message(raw)) == "Printer jam\n\nUnit 4B"


def test_quoted_reply_history_is_dropped(parser: Parser) -> None:
    body = "Still broken after restart.\n\nOn Mon, 14 Sep 2026, IT wrote:\n> Try a restart"

    assert parser.clean(body) == "Still broken after restart."


def test_outlook_reply_header_is_dropped(parser: Parser) -> None:
    body = "Same problem today.\n\n________________\nFrom: Service Desk\nSent: Monday"

    assert parser.clean(body) == "Same problem today."


@pytest.mark.parametrize(
    "footer",
    [
        "Thanks,\nDana\nRN, Unit 4B",
        "-- \nDana Nurse | Contoso Health",
        "Sent from my iPhone",
        "CONFIDENTIALITY NOTICE: this message is intended only for...",
    ],
)
def test_signatures_and_footers_are_dropped(parser: Parser, footer: str) -> None:
    assert parser.clean(f"Scanner not reading wristbands.\n\n{footer}") == (
        "Scanner not reading wristbands."
    )


def test_sign_off_words_inside_a_sentence_are_kept(parser: Parser) -> None:
    body = "Thanks, it crashed again at 9am.\nBest option is a new laptop."

    assert parser.clean(body) == body


def test_markers_before_any_content_are_kept_so_forwards_survive(parser: Parser) -> None:
    assert parser.clean("> EMR login fails with ERR-4012\nplease help") == (
        "> EMR login fails with ERR-4012\nplease help"
    )


def test_whitespace_is_normalised(parser: Parser) -> None:
    assert parser.clean("  first\t\tline  \r\n\r\n\r\n\r\nsecond ") == "first line\n\nsecond"


def test_web_form_body_is_not_mime_parsed(parser: Parser) -> None:
    body = "Content-Type: text/html\n\nWi-Fi drops in the ICU"

    assert parser.parse(_message(body, Channel.WEB_FORM)) == body


def test_script_contents_are_not_text() -> None:
    assert html_to_text("<script>alert(1)</script>ok").strip() == "ok"
