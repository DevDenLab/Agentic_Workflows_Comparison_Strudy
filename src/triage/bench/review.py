"""Label review sheet: the golden set as a CSV a reviewer checks row by row in a spreadsheet.

The reviewer edits label cells in place and fills `reviewer_verdict` (ok / change) and notes.
"""

import csv
from pathlib import Path

from triage.bench.golden import GoldenCase, GoldenSet, Split

COLUMNS = (
    "id",
    "split",
    "subtype",
    "channel",
    "sender",
    "subject",
    "body",
    "category",
    "impact",
    "urgency",
    "priority",
    "assignment_group",
    "handling",
    "alternatives",
    "rationale",
    "reviewer_verdict",
    "reviewer_notes",
)
_SPLIT_ORDER = list(Split)


def write_review_sheet(golden: GoldenSet, path: Path) -> int:
    """Write one row per case, ordered by split then id. Returns the row count.

    UTF-8 with a byte-order mark, so Excel shows accented text correctly.
    """
    cases = sorted(golden.cases, key=lambda c: (_SPLIT_ORDER.index(c.split), c.id))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(_row(case) for case in cases)
    return len(cases)


def _row(case: GoldenCase) -> dict[str, str]:
    label = case.label
    return {
        "id": case.id,
        "split": case.split.value,
        "subtype": case.subtype.value,
        "channel": case.input.channel.value,
        "sender": case.input.sender,
        "subject": case.input.subject,
        "body": case.input.body.strip(),
        "category": label.category or "",
        "impact": label.impact or "",
        "urgency": label.urgency or "",
        "priority": label.priority.value if label.priority else "",
        "assignment_group": label.assignment_group or "",
        "handling": label.handling.value,
        "alternatives": "; ".join(
            f"{alt.category} / {alt.assignment_group} / {alt.priority.value}"
            for alt in label.alternatives
        ),
        "rationale": case.rationale,
        "reviewer_verdict": "",
        "reviewer_notes": "",
    }
