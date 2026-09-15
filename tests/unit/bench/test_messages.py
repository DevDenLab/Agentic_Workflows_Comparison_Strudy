from collections.abc import Callable
from datetime import UTC, datetime
from email import message_from_string, policy
from email.message import EmailMessage

from triage.bench.golden import GoldenCase
from triage.bench.messages import to_message
from triage.contracts import Channel

CaseFactory = Callable[..., GoldenCase]
RECEIVED = datetime(2026, 9, 14, 16, 0, tzinfo=UTC)
ADDRESS = "servicedesk@contoso.example"


def test_email_case_becomes_a_parseable_rfc822_message(make_case: CaseFactory) -> None:
    body = "Bonjour, mon mot de passe est refusé.\n\nMerci"
    case = make_case(subject="Connexion", body=body)

    message = to_message(case, received_at=RECEIVED, service_desk_address=ADDRESS)

    parsed = message_from_string(message.raw_body, policy=policy.default)
    assert isinstance(parsed, EmailMessage)
    part = parsed.get_body(preferencelist=("plain",))
    assert part is not None
    assert part.get_content().strip() == body
    assert parsed["Message-ID"] == message.message_id == "<golden-adv-001@bench.contoso.example>"
    assert parsed["From"] == "kevin.nguyen@contoso.example"
    assert parsed["To"] == ADDRESS
    assert parsed["Subject"] == "Connexion"
    assert message.channel is Channel.EMAIL
    assert message.received_at == RECEIVED


def test_web_form_case_keeps_the_body_as_submitted(make_case: CaseFactory) -> None:
    case = make_case(channel="web_form", body="Wi-Fi drops in the ICU")

    message = to_message(case, received_at=RECEIVED, service_desk_address=ADDRESS)

    assert message.channel is Channel.WEB_FORM
    assert message.message_id == "webform:golden-ADV-001"
    assert message.raw_body == "Wi-Fi drops in the ICU"


def test_same_case_always_produces_the_same_message(make_case: CaseFactory) -> None:
    case = make_case()

    first = to_message(case, received_at=RECEIVED, service_desk_address=ADDRESS)
    second = to_message(case, received_at=RECEIVED, service_desk_address=ADDRESS)

    assert first == second
