from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from triage.api import create_app
from triage.clock import FixedClock
from triage.config import Settings
from triage.container import build_container

SUBMISSION = {
    "submission_id": "F-1001",
    "email": "kevin.nguyen@contoso.example",
    "subject": "VPN",
    "description": "My VPN keeps dropping every few minutes.",
}


@pytest.fixture
def client(config_dir: Path, data_dir: Path, tmp_path: Path) -> TestClient:
    settings = Settings(
        _env_file=None,
        config_dir=config_dir,
        data_dir=data_dir,
        var_dir=tmp_path / "var",
        log_level="WARNING",
    )
    container = build_container(settings, clock=FixedClock(datetime(2026, 9, 14, 15, tzinfo=UTC)))
    return TestClient(create_app(container))


def test_web_form_submission_is_triaged(client: TestClient) -> None:
    response = client.post("/tickets", json=SUBMISSION)

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "auto_resolved"
    assert body["decision"]["category"] == "network_connectivity"
    assert body["message_id"] == "webform:F-1001"


@pytest.mark.parametrize(
    "payload",
    [
        {k: v for k, v in SUBMISSION.items() if k != "description"},
        SUBMISSION | {"priority": "P1"},
    ],
    ids=["missing field", "unknown field"],
)
def test_malformed_submission_is_rejected_before_triage(
    client: TestClient, payload: dict[str, str]
) -> None:
    assert client.post("/tickets", json=payload).status_code == 422
    assert "triage_tickets_total{" not in client.get("/metrics").text


def test_metrics_endpoint_serves_prometheus_text(client: TestClient) -> None:
    client.post("/tickets", json=SUBMISSION)

    response = client.get("/metrics")

    assert response.headers["content-type"].startswith("text/plain")
    assert 'triage_rule_hits_total{rule_id="R040"} 1.0' in response.text


def test_health(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
