from pathlib import Path

import pytest

from triage.config import LoadedConfig, load_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def config_dir() -> Path:
    return PROJECT_ROOT / "config"


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return PROJECT_ROOT / "data"


@pytest.fixture(scope="session")
def loaded_config(config_dir: Path) -> LoadedConfig:
    return load_config(config_dir)
