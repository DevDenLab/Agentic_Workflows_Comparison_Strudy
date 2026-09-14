"""Step 6 — CMDB Lookup: who raised the ticket, their department and services, and the asset.

`SqliteCmdb.lookup` backs both v1's pipeline step and v2's `cmdb_lookup` tool.
It returns facts only; turning facts into impact is the priority matrix's job.
"""

import sqlite3
from contextlib import closing
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict


class Criticality(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Employee(_Record):
    employee_id: str
    full_name: str
    email: str
    role: str


class Department(_Record):
    department_id: str
    name: str
    site: str
    clinical: bool


class Service(_Record):
    service_id: str
    name: str
    criticality: Criticality


class Asset(_Record):
    asset_tag: str
    asset_type: str
    model: str
    service: Service
    assigned_to: str | None


class CmdbContext(_Record):
    employee: Employee | None = None
    department: Department | None = None
    services: tuple[Service, ...] = ()
    asset: Asset | None = None
    notes: tuple[str, ...] = ()
    """Lookups that found nothing, e.g. an employee id in the ticket that the CMDB doesn't have."""


class Cmdb(Protocol):
    def lookup(
        self,
        *,
        employee_id: str | None = None,
        email: str | None = None,
        asset_tag: str | None = None,
    ) -> CmdbContext: ...


class SqliteCmdb:
    """Read-only access: connections use mode=ro, so a bug here cannot modify the CMDB."""

    def __init__(self, db_path: Path) -> None:
        if not db_path.is_file():
            raise FileNotFoundError(f"CMDB database not found: {db_path}")
        self._uri = f"{db_path.resolve().as_uri()}?mode=ro"

    def lookup(
        self,
        *,
        employee_id: str | None = None,
        email: str | None = None,
        asset_tag: str | None = None,
    ) -> CmdbContext:
        notes: list[str] = []
        with closing(sqlite3.connect(self._uri, uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            employee_row = None
            if employee_id:
                employee_row = conn.execute(
                    "SELECT * FROM employees WHERE employee_id = ?", (employee_id,)
                ).fetchone()
                if employee_row is None:
                    notes.append(f"employee {employee_id} not in CMDB")
            if employee_row is None and email:
                employee_row = conn.execute(
                    "SELECT * FROM employees WHERE email = ?", (email,)
                ).fetchone()
                if employee_row is None:
                    notes.append(f"sender {email} not in CMDB")

            department: Department | None = None
            services: tuple[Service, ...] = ()
            if employee_row is not None:
                department, services = self._department(conn, employee_row["department_id"])

            asset = self._asset(conn, asset_tag, notes) if asset_tag else None

        return CmdbContext(
            employee=_employee(employee_row) if employee_row is not None else None,
            department=department,
            services=services,
            asset=asset,
            notes=tuple(notes),
        )

    @staticmethod
    def _department(
        conn: sqlite3.Connection, department_id: str
    ) -> tuple[Department, tuple[Service, ...]]:
        row = conn.execute(
            "SELECT * FROM departments WHERE department_id = ?", (department_id,)
        ).fetchone()
        service_rows = conn.execute(
            "SELECT s.* FROM services s "
            "JOIN department_services ds ON ds.service_id = s.service_id "
            "WHERE ds.department_id = ? "
            "ORDER BY CASE s.criticality WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, "
            "s.service_id",
            (department_id,),
        ).fetchall()
        department = Department(
            department_id=row["department_id"],
            name=row["name"],
            site=row["site"],
            clinical=bool(row["clinical"]),
        )
        return department, tuple(_service(r) for r in service_rows)

    @staticmethod
    def _asset(conn: sqlite3.Connection, asset_tag: str, notes: list[str]) -> Asset | None:
        row = conn.execute(
            "SELECT a.asset_tag, a.asset_type, a.model, a.assigned_to, "
            "s.service_id, s.name, s.criticality "
            "FROM assets a JOIN services s ON s.service_id = a.service_id "
            "WHERE a.asset_tag = ?",
            (asset_tag,),
        ).fetchone()
        if row is None:
            notes.append(f"asset {asset_tag} not in CMDB")
            return None
        return Asset(
            asset_tag=row["asset_tag"],
            asset_type=row["asset_type"],
            model=row["model"],
            service=_service(row),
            assigned_to=row["assigned_to"],
        )


def _employee(row: sqlite3.Row) -> Employee:
    return Employee(
        employee_id=row["employee_id"],
        full_name=row["full_name"],
        email=row["email"],
        role=row["role"],
    )


def _service(row: sqlite3.Row) -> Service:
    return Service(service_id=row["service_id"], name=row["name"], criticality=row["criticality"])


def create_cmdb(db_path: Path, schema_sql: Path, seed_sql: Path) -> None:
    """(Re)build the CMDB file from SQL. Fails if the seed breaks a foreign key."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(schema_sql.read_text(encoding="utf-8"))
        conn.executescript(seed_sql.read_text(encoding="utf-8"))
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise ValueError(f"CMDB seed breaks foreign keys: {violations}")
        conn.commit()
