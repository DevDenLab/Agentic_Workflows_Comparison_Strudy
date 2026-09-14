import sqlite3
from pathlib import Path

import pytest

from triage.v1.cmdb import Criticality, SqliteCmdb, create_cmdb


@pytest.fixture(scope="module")
def cmdb(data_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> SqliteCmdb:
    db_path = tmp_path_factory.mktemp("cmdb") / "cmdb.sqlite3"
    create_cmdb(db_path, data_dir / "cmdb" / "schema.sql", data_dir / "cmdb" / "seed.sql")
    return SqliteCmdb(db_path)


def test_employee_id_lookup_returns_department_and_services(cmdb: SqliteCmdb) -> None:
    context = cmdb.lookup(employee_id="E100201")

    assert context.employee is not None
    assert context.employee.full_name == "Priya Raman"
    assert context.department is not None
    assert context.department.department_id == "ICU"
    assert context.department.clinical is True
    assert context.notes == ()


def test_services_are_ordered_most_critical_first(cmdb: SqliteCmdb) -> None:
    services = cmdb.lookup(employee_id="E100701").services

    criticalities = [s.criticality for s in services]
    ranks = [list(Criticality).index(c) for c in criticalities]
    assert ranks == sorted(ranks)
    assert services[-1].criticality is Criticality.LOW


def test_email_lookup_is_case_insensitive(cmdb: SqliteCmdb) -> None:
    context = cmdb.lookup(email="Kevin.Nguyen@CONTOSO.example")

    assert context.employee is not None
    assert context.employee.employee_id == "E100701"


def test_employee_id_takes_precedence_over_sender_email(cmdb: SqliteCmdb) -> None:
    context = cmdb.lookup(employee_id="E100401", email="samir.patel@contoso.example")

    assert context.employee is not None
    assert context.employee.employee_id == "E100401"


def test_unknown_employee_id_falls_back_to_email_and_says_so(cmdb: SqliteCmdb) -> None:
    context = cmdb.lookup(employee_id="E999999", email="liam.chen@contoso.example")

    assert context.employee is not None
    assert context.employee.employee_id == "E100302"
    assert context.notes == ("employee E999999 not in CMDB",)


def test_asset_lookup_includes_its_service(cmdb: SqliteCmdb) -> None:
    asset = cmdb.lookup(asset_tag="CH-WOW-00007").asset

    assert asset is not None
    assert asset.asset_type == "workstation_on_wheels"
    assert asset.service.service_id == "clinical_device_fleet"
    assert asset.service.criticality is Criticality.HIGH
    assert asset.assigned_to is None


def test_nothing_found_is_an_empty_context_with_notes(cmdb: SqliteCmdb) -> None:
    context = cmdb.lookup(email="stranger@example.org", asset_tag="CH-LT-99999")

    assert context.employee is None
    assert context.department is None
    assert context.asset is None
    assert context.services == ()
    assert context.notes == (
        "sender stranger@example.org not in CMDB",
        "asset CH-LT-99999 not in CMDB",
    )


def test_missing_database_fails_at_construction(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        SqliteCmdb(tmp_path / "absent.sqlite3")


def test_seed_that_breaks_a_foreign_key_is_rejected(data_dir: Path, tmp_path: Path) -> None:
    bad_seed = tmp_path / "seed.sql"
    bad_seed.write_text(
        "INSERT INTO services VALUES ('emr', 'EMR', 'high');\n"
        "INSERT INTO assets VALUES ('CH-LT-00001', 'laptop', 'x', 'no_such_service', NULL);\n",
        encoding="utf-8",
    )

    with pytest.raises((ValueError, sqlite3.IntegrityError)):
        create_cmdb(tmp_path / "bad.sqlite3", data_dir / "cmdb" / "schema.sql", bad_seed)
