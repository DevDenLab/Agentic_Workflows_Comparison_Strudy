"""Configuration from two sources, split by purpose.

- Environment (`Settings`): what differs per machine. Endpoints, secrets, paths, log format.
- YAML under config/ (`load_model`): what changes behaviour. Versioned, reviewed in PRs, diffable.

Both are validated at start-up. A bad file fails loudly before any ticket is processed.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from platformdirs import user_state_dir
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    ValidationError,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from triage.contracts import Taxonomy

APP_NAME = "service-desk-triage"


class ConfigError(Exception):
    """A config file is missing, unparseable or invalid."""


class ConfigModel(BaseModel):
    """Base for YAML-backed config: immutable, and a misspelt key is an error."""

    model_config = ConfigDict(frozen=True, extra="forbid")


def _compiles(pattern: str) -> str:
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"invalid regex {pattern!r}: {exc}") from exc
    return pattern


RegexPattern = Annotated[str, AfterValidator(_compiles)]
SemVer = Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+$")]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    triage_model: str | None = None
    critic_model: str | None = None

    config_dir: Path = Path("config")
    data_dir: Path = Path("data")
    var_dir: Path = Field(default_factory=lambda: Path(user_state_dir(APP_NAME, appauthor=False)))

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "json"

    @property
    def llm_configured(self) -> bool:
        """v1 needs no model, so the LLM settings are optional until an LLM pipeline is built."""
        return bool(self.llm_base_url and self.llm_api_key and self.triage_model)


class AppConfig(ConfigModel):
    """config/settings.yaml"""

    schema_version: Literal[1]
    organisation: str = Field(min_length=1)
    timezone: str

    @field_validator("timezone")
    @classmethod
    def _timezone_exists(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown IANA timezone {value!r}") from exc
        return value


@dataclass(frozen=True, slots=True)
class LoadedConfig:
    app: AppConfig
    taxonomy: Taxonomy


def _read_yaml(path: Path) -> object:
    try:
        with path.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except FileNotFoundError as exc:
        raise ConfigError(f"{path}: file not found") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: not valid YAML: {exc}") from exc


def load_model[M: BaseModel](model: type[M], path: Path) -> M:
    """Read one YAML file into `model`. Every failure becomes a ConfigError naming the file."""
    try:
        return model.model_validate(_read_yaml(path))
    except ValidationError as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def load_config(config_dir: Path) -> LoadedConfig:
    return LoadedConfig(
        app=load_model(AppConfig, config_dir / "settings.yaml"),
        taxonomy=load_model(Taxonomy, config_dir / "taxonomy.yaml"),
    )
