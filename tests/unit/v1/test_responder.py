import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from jinja2 import UndefinedError

from triage.config import ConfigError, LoadedConfig
from triage.contracts import Channel, ExtractedFields, Priority, Ticket
from triage.v1.cmdb import CmdbContext, Employee
from triage.v1.responder import Responder
from triage.v1.settings import V1Config

DUE = datetime(2026, 9, 15, 21, 0, tzinfo=UTC)  # 15:00 in Edmonton (MDT)
DANA = Employee(
    employee_id="E100101",
    full_name="Dana Whitfield",
    email="dana.whitfield@contoso.example",
    role="Registered Nurse",
)


def _ticket(subject: str = "VPN keeps dropping") -> Ticket:
    return Ticket(
        correlation_id=uuid4(),
        message_id="m-1",
        channel=Channel.EMAIL,
        received_at=datetime(2026, 9, 14, 15, 0, tzinfo=UTC),
        sender="dana.whitfield@contoso.example",
        subject=subject,
        text="VPN drops",
        extracted=ExtractedFields(),
    )


@pytest.fixture(scope="module")
def responder(v1_config: V1Config, loaded_config: LoadedConfig) -> Responder:
    return Responder(v1_config.templates_dir, loaded_config.taxonomy, loaded_config.app.timezone)


def _render(responder: Responder, category: str, context: CmdbContext) -> str:
    return responder.render(
        ticket=_ticket(),
        category=category,
        priority=Priority.P3,
        assignment_group="network_operations",
        due_at=DUE,
        context=context,
    )


def test_every_category_renders(responder: Responder, loaded_config: LoadedConfig) -> None:
    for category in loaded_config.taxonomy.category_ids:
        reply = _render(responder, category, CmdbContext(employee=DANA))

        assert reply.startswith("Hello Dana,")
        assert '"VPN keeps dropping" as a P3 request for the Network Operations team' in reply
        assert "Tue 15 Sep 2026, 15:00 MDT" in reply


def test_category_advice_is_included(responder: Responder) -> None:
    reply = _render(responder, "security_incident", CmdbContext())

    assert "Do not click any more links" in reply


def test_unknown_requester_gets_a_generic_greeting(responder: Responder) -> None:
    assert _render(responder, "printing", CmdbContext()).startswith("Hello there,")


def test_missing_template_fails_at_start_up(
    v1_config: V1Config, loaded_config: LoadedConfig, tmp_path: Path
) -> None:
    templates = tmp_path / "templates"
    shutil.copytree(v1_config.templates_dir, templates)
    (templates / "printing.j2").unlink()

    with pytest.raises(ConfigError, match="printing"):
        Responder(templates, loaded_config.taxonomy, loaded_config.app.timezone)


def test_undefined_template_variable_raises_instead_of_rendering_blank(
    v1_config: V1Config, loaded_config: LoadedConfig, tmp_path: Path
) -> None:
    templates = tmp_path / "templates"
    shutil.copytree(v1_config.templates_dir, templates)
    (templates / "printing.j2").write_text("Hi {{ ticket_number }}", encoding="utf-8")
    responder = Responder(templates, loaded_config.taxonomy, loaded_config.app.timezone)

    with pytest.raises(UndefinedError):
        _render(responder, "printing", CmdbContext())
