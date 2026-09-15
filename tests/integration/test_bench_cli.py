"""`triage bench` end to end on a tiny test-owned golden set (never the real one)."""

import json
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from triage.bench.report import load_summary
from triage.cli import app


def _case(
    case_id: str, subtype: str, channel: str, body: str, label: dict[str, str]
) -> dict[str, object]:
    return {
        "id": case_id,
        "subtype": subtype,
        "input": {
            "channel": channel,
            "sender": "kevin.nguyen@contoso.example",
            "subject": "Help",
            "body": body,
        },
        "label": label,
        "rationale": "test",
    }


NETWORK_P4 = {
    "category": "network_connectivity",
    "impact": "low",
    "urgency": "medium",
    "priority": "P4",
    "assignment_group": "network_operations",
    "handling": "auto",
}
ADMIN_RIGHTS = {
    "category": "access_identity",
    "impact": "low",
    "urgency": "low",
    "priority": "P4",
    "assignment_group": "identity_access",
    "handling": "escalate",
}
CASES = {
    "in_dist.yaml": (
        "in_dist",
        _case("IND-001", "standard", "email", "VPN disconnects every 15 minutes.", NETWORK_P4),
    ),
    "ood.yaml": (
        "ood",
        _case("OOD-001", "standard", "web_form", "None of the work sites load.", NETWORK_P4),
    ),
    "adversarial.yaml": (
        "adversarial",
        _case(
            "ADV-001",
            "must_escalate",
            "email",
            "Please make me a local administrator on my laptop.",
            ADMIN_RIGHTS,
        ),
    ),
}


def _write_data_dir(real_data: Path, target: Path, *, reviewed: bool) -> None:
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(real_data / "cmdb", target / "cmdb")
    golden = target / "golden"
    golden.mkdir(parents=True)
    for filename, (split, case) in CASES.items():
        document: dict[str, object] = {"split": split}
        if reviewed:
            document |= {"reviewed_by": "Test Reviewer", "reviewed_on": "2026-09-15"}
        document["cases"] = [case]
        text = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
        (golden / filename).write_text(text, encoding="utf-8")


@pytest.fixture
def runner(config_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("VAR_DIR", str(tmp_path / "var"))
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    return CliRunner()


def test_bench_refuses_unreviewed_labels(runner: CliRunner, data_dir: Path, tmp_path: Path) -> None:
    _write_data_dir(data_dir, tmp_path / "data", reviewed=False)

    result = runner.invoke(app, ["bench"])

    assert result.exit_code == 2
    assert "not been reviewed" in result.output


def test_bench_writes_results_summary_and_charts_then_passes_its_own_baseline(
    runner: CliRunner, data_dir: Path, tmp_path: Path
) -> None:
    _write_data_dir(data_dir, tmp_path / "data", reviewed=True)

    first = runner.invoke(app, ["bench", "--repeats", "2", "--out", str(tmp_path / "reports")])

    assert first.exit_code == 0, first.output
    target = tmp_path / "reports" / "v1_conventional"
    assert {p.name for p in target.iterdir()} == {
        "results.jsonl",
        "summary.json",
        "summary.md",
        "outcomes.png",
        "rates.png",
    }
    lines = (target / "results.jsonl").read_text(encoding="utf-8").splitlines()
    assert len([json.loads(line) for line in lines]) == 6
    summary = load_summary(target / "summary.json")
    assert summary.repeats == 2
    assert summary.overall.stable_tickets.successes == 3

    again = runner.invoke(
        app,
        ["bench", "--out", str(tmp_path / "again"), "--baseline", str(target / "summary.json")],
    )

    assert again.exit_code == 0, again.output
    assert "no regression" in again.output
