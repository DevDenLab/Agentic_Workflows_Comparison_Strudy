from collections.abc import Callable
from pathlib import Path

import pytest

from triage.config import LoadedConfig
from triage.v1.cmdb import Asset, CmdbContext, Criticality, Department, Service
from triage.v1.settings import V1Config, load_v1_config


@pytest.fixture(scope="session")
def v1_config(config_dir: Path, loaded_config: LoadedConfig) -> V1Config:
    return load_v1_config(config_dir, loaded_config.taxonomy)


@pytest.fixture(scope="session")
def make_context() -> Callable[..., CmdbContext]:
    """Build a CmdbContext without a database: `make_context(clinical=True, asset_service=...)`."""

    def _make(
        *,
        clinical: bool | None = None,
        asset_service: str | None = None,
        asset_criticality: Criticality = Criticality.MEDIUM,
    ) -> CmdbContext:
        department = (
            Department(department_id="ICU", name="ICU", site="Foothills", clinical=clinical)
            if clinical is not None
            else None
        )
        asset = (
            Asset(
                asset_tag="CH-WOW-00007",
                asset_type="workstation_on_wheels",
                model="cart",
                service=Service(
                    service_id=asset_service, name=asset_service, criticality=asset_criticality
                ),
                assigned_to=None,
            )
            if asset_service is not None
            else None
        )
        return CmdbContext(department=department, asset=asset)

    return _make
