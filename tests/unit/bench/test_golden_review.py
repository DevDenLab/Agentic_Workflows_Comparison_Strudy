"""The benchmark refuses unreviewed labels, so the review marker itself is tested."""

import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from triage.bench.golden import SPLIT_FILES, GoldenFile, load_golden_set

CASE = {
    "id": "IND-001",
    "subtype": "standard",
    "input": {
        "channel": "email",
        "sender": "kevin.nguyen@contoso.example",
        "subject": "VPN",
        "body": "VPN is down",
    },
    "label": {
        "category": "network_connectivity",
        "impact": "low",
        "urgency": "medium",
        "priority": "P4",
        "assignment_group": "network_operations",
        "handling": "auto",
    },
    "rationale": "test",
}


def test_reviewer_and_date_must_be_set_together() -> None:
    with pytest.raises(ValidationError, match="set together"):
        GoldenFile.model_validate({"split": "in_dist", "reviewed_by": "T. Joshi", "cases": [CASE]})


def test_golden_set_is_reviewed_only_when_every_file_names_a_reviewer(
    data_dir: Path, tmp_path: Path
) -> None:
    golden_dir = tmp_path / "golden"
    shutil.copytree(data_dir / "golden", golden_dir)

    def sign(filename: str) -> None:
        path = golden_dir / filename
        text = path.read_text(encoding="utf-8")
        split_line = next(line for line in text.splitlines() if line.startswith("split:"))
        signed = f"{split_line}\nreviewed_by: T. Joshi\nreviewed_on: 2026-09-15"
        path.write_text(text.replace(split_line, signed, 1), encoding="utf-8")

    filenames = list(SPLIT_FILES.values())
    for filename in filenames[:-1]:
        sign(filename)
    assert not load_golden_set(golden_dir).reviewed

    sign(filenames[-1])
    assert load_golden_set(golden_dir).reviewed
