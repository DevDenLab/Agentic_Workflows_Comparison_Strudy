import csv
from pathlib import Path

import pytest

from triage.bench.golden import GoldenSet, load_golden_set
from triage.bench.review import COLUMNS, write_review_sheet


@pytest.fixture(scope="module")
def rows(data_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> list[dict[str, str]]:
    golden: GoldenSet = load_golden_set(data_dir / "golden")
    path = tmp_path_factory.mktemp("review") / "label-review.csv"

    assert write_review_sheet(golden, path) == len(golden.cases)

    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        assert tuple(reader.fieldnames or ()) == COLUMNS
        return list(reader)


def _row(rows: list[dict[str, str]], case_id: str) -> dict[str, str]:
    (row,) = [r for r in rows if r["id"] == case_id]
    return row


def test_one_row_per_case_ordered_by_split_then_id(rows: list[dict[str, str]]) -> None:
    ids = [row["id"] for row in rows]

    assert len(ids) == 150
    assert ids[0] == "IND-001"
    assert ids[50] == "OOD-001"
    assert ids[-1] == "ADV-050"


def test_multiline_bodies_and_accents_survive(rows: list[dict[str, str]]) -> None:
    assert "\n" in _row(rows, "IND-025")["body"]
    assert "à mon compte" in _row(rows, "OOD-046")["body"]


def test_undeterminable_labels_are_blank(rows: list[dict[str, str]]) -> None:
    row = _row(rows, "ADV-031")

    assert row["category"] == row["priority"] == row["assignment_group"] == ""
    assert row["handling"] == "escalate"


def test_alternatives_are_readable(rows: list[dict[str, str]]) -> None:
    assert _row(rows, "ADV-038")["alternatives"] == "network_connectivity / network_operations / P3"


def test_reviewer_columns_start_empty(rows: list[dict[str, str]]) -> None:
    assert {row["reviewer_verdict"] for row in rows} == {""}
