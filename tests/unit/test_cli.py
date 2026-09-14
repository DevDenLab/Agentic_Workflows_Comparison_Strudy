from pathlib import Path

import pytest
from typer.testing import CliRunner

from triage.cli import app


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Run from an empty directory so a developer's real .env is never read."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VAR_DIR", str(tmp_path / "var"))
    for var in ("LLM_BASE_URL", "LLM_API_KEY", "TRIAGE_MODEL", "CRITIC_MODEL"):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_config_check_passes_on_shipped_config(
    isolated_env: pytest.MonkeyPatch, config_dir: Path
) -> None:
    isolated_env.setenv("CONFIG_DIR", str(config_dir))

    result = CliRunner().invoke(app, ["config-check"])

    assert result.exit_code == 0, result.output
    assert "Contoso Health" in result.output
    assert "not configured (v1 needs none)" in result.output


def test_config_check_exits_nonzero_on_broken_config(
    isolated_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    isolated_env.setenv("CONFIG_DIR", str(tmp_path / "missing"))

    result = CliRunner().invoke(app, ["config-check"])

    assert result.exit_code == 1
