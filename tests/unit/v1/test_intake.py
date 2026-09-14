from datetime import UTC, datetime
from pathlib import Path

from triage.clock import FixedClock
from triage.contracts import Channel
from triage.v1.intake import UNKNOWN_SENDER, EmailFileIntake, WebFormIntake, WebFormSubmission

NOW = datetime(2026, 9, 14, 15, 0, tzinfo=UTC)


def _raw(headers: dict[str, str], body: str = "My VPN disconnects every 10 minutes.") -> str:
    lines = [f"{name}: {value}" for name, value in headers.items()]
    return "\r\n".join([*lines, "Content-Type: text/plain; charset=utf-8", "", body, ""])


FULL_HEADERS = {
    "Message-ID": "<abc123@contoso.example>",
    "Date": "Mon, 14 Sep 2026 08:15:00 -0600",
    "From": "Dana Nurse <dana.nurse@contoso.example>",
    "Subject": "VPN keeps dropping",
}


def test_email_headers_become_message_fields() -> None:
    raw = _raw(FULL_HEADERS)

    message = EmailFileIntake(FixedClock(NOW)).from_raw(raw)

    assert message.message_id == "<abc123@contoso.example>"
    assert message.channel is Channel.EMAIL
    assert message.received_at == datetime(2026, 9, 14, 14, 15, tzinfo=UTC)
    assert message.sender == "dana.nurse@contoso.example"
    assert message.subject == "VPN keeps dropping"
    assert message.raw_body == raw


def test_missing_message_id_falls_back_to_a_stable_content_hash() -> None:
    raw = _raw({k: v for k, v in FULL_HEADERS.items() if k != "Message-ID"})
    intake = EmailFileIntake(FixedClock(NOW))

    first, second = intake.from_raw(raw), intake.from_raw(raw)

    assert first.message_id.startswith("sha256:")
    assert first.message_id == second.message_id


def test_missing_or_timezone_less_date_uses_the_clock() -> None:
    intake = EmailFileIntake(FixedClock(NOW))
    no_date = {k: v for k, v in FULL_HEADERS.items() if k != "Date"}
    unknown_zone = FULL_HEADERS | {"Date": "Mon, 14 Sep 2026 08:15:00 -0000"}

    assert intake.from_raw(_raw(no_date)).received_at == NOW
    assert intake.from_raw(_raw(unknown_zone)).received_at == NOW


def test_missing_sender_is_marked_unknown() -> None:
    raw = _raw({k: v for k, v in FULL_HEADERS.items() if k != "From"})

    assert EmailFileIntake(FixedClock(NOW)).from_raw(raw).sender == UNKNOWN_SENDER


def test_directory_is_read_in_name_order(tmp_path: Path) -> None:
    for name in ("b", "a"):
        headers = FULL_HEADERS | {"Message-ID": f"<{name}@contoso.example>"}
        (tmp_path / f"{name}.eml").write_text(_raw(headers), encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")

    ids = [m.message_id for m in EmailFileIntake(FixedClock(NOW)).read_directory(tmp_path)]

    assert ids == ["<a@contoso.example>", "<b@contoso.example>"]


def test_web_form_submission_becomes_a_message() -> None:
    submission = WebFormSubmission(
        submission_id="F-1001",
        email="sam.porter@contoso.example",
        subject="  Label printer jammed ",
        description="Unit 4B wristband printer is jammed.",
    )

    message = WebFormIntake(FixedClock(NOW)).receive(submission)

    assert message.message_id == "webform:F-1001"
    assert message.channel is Channel.WEB_FORM
    assert message.received_at == NOW
    assert message.subject == "Label printer jammed"
    assert message.raw_body == "Unit 4B wristband printer is jammed."
