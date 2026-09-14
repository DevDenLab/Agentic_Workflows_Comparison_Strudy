import shutil
from pathlib import Path

import pytest

from triage.config import ConfigError, Settings, load_config

LLM_ENV_VARS = ("LLM_BASE_URL", "LLM_API_KEY", "TRIAGE_MODEL", "CRITIC_MODEL")


@pytest.fixture
def config_copy(config_dir: Path, tmp_path: Path) -> Path:
    target = tmp_path / "config"
    shutil.copytree(config_dir, target)
    return target


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for var in LLM_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_shipped_config_loads(config_dir: Path) -> None:
    loaded = load_config(config_dir)
    assert loaded.app.timezone == "America/Edmonton"


def test_unknown_key_fails_fast_and_names_the_file(config_copy: Path) -> None:
    settings = config_copy / "settings.yaml"
    settings.write_text(settings.read_text(encoding="utf-8") + "retries: 3\n", encoding="utf-8")

    with pytest.raises(ConfigError, match=r"settings\.yaml"):
        load_config(config_copy)


def test_invalid_timezone_fails_fast(config_copy: Path) -> None:
    settings = config_copy / "settings.yaml"
    text = settings.read_text(encoding="utf-8").replace("America/Edmonton", "Alberta/Calgary")
    settings.write_text(text, encoding="utf-8")

    with pytest.raises(ConfigError, match="unknown IANA timezone"):
        load_config(config_copy)


def test_missing_file_fails_fast(config_copy: Path) -> None:
    (config_copy / "taxonomy.yaml").unlink()

    with pytest.raises(ConfigError, match=r"taxonomy\.yaml: file not found"):
        load_config(config_copy)


def test_llm_settings_come_from_environment(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("LLM_BASE_URL", "https://api.deepseek.com")
    clean_env.setenv("LLM_API_KEY", "sk-test")
    clean_env.setenv("TRIAGE_MODEL", "deepseek-flash")

    settings = Settings(_env_file=None)

    assert settings.llm_configured
    assert settings.triage_model == "deepseek-flash"


def test_llm_is_optional_for_v1(clean_env: pytest.MonkeyPatch) -> None:
    assert not Settings(_env_file=None).llm_configured


def test_api_key_never_appears_in_repr(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("LLM_API_KEY", "sk-very-secret")

    settings = Settings(_env_file=None)

    assert "sk-very-secret" not in repr(settings)
    assert settings.llm_api_key is not None
    assert settings.llm_api_key.get_secret_value() == "sk-very-secret"
