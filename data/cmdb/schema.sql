-- Configuration management database for the fictional Contoso Health.
-- Read by v1 step 6 (CMDB Lookup) and by the v2 cmdb_lookup tool, through triage.v1.cmdb.SqliteCmdb.

CREATE TABLE departments (
    department_id TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    site          TEXT NOT NULL,
    clinical      INTEGER NOT NULL CHECK (clinical IN (0, 1))
);

CREATE TABLE services (
    service_id  TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    criticality TEXT NOT NULL CHECK (criticality IN ('high', 'medium', 'low'))
);

CREATE TABLE employees (
    employee_id   TEXT PRIMARY KEY,
    full_name     TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    department_id TEXT NOT NULL REFERENCES departments (department_id),
    role          TEXT NOT NULL
);

CREATE TABLE department_services (
    department_id TEXT NOT NULL REFERENCES departments (department_id),
    service_id    TEXT NOT NULL REFERENCES services (service_id),
    PRIMARY KEY (department_id, service_id)
);

CREATE TABLE assets (
    asset_tag   TEXT PRIMARY KEY,
    asset_type  TEXT NOT NULL,
    model       TEXT NOT NULL,
    service_id  TEXT NOT NULL REFERENCES services (service_id),
    assigned_to TEXT REFERENCES employees (employee_id)
);
