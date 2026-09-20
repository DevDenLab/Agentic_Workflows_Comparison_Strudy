"""Feedback loop — docs/flows.md: a human correction becomes a new labelled eval case.

Kept separate from the reviewed golden set (data/golden/feedback.jsonl, not data/golden/*.yaml):
a correction is a candidate case, not automatically part of the benchmark. A human curates it into
one of the reviewed splits deliberately, the same way every other golden case was reviewed.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from triage.contracts import TriageDecision


@dataclass(frozen=True, slots=True)
class Correction:
    message_id: str
    subject: str
    body: str
    sender: str
    original_decision: TriageDecision | None
    original_outcome: str
    corrected_decision: TriageDecision
    corrected_by: str
    note: str
    corrected_at: datetime


class FeedbackStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def record(self, correction: Correction) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "message_id": correction.message_id,
            "subject": correction.subject,
            "body": correction.body,
            "sender": correction.sender,
            "original_decision": (
                correction.original_decision.model_dump(mode="json")
                if correction.original_decision
                else None
            ),
            "original_outcome": correction.original_outcome,
            "corrected_decision": correction.corrected_decision.model_dump(mode="json"),
            "corrected_by": correction.corrected_by,
            "note": correction.note,
            "corrected_at": correction.corrected_at.isoformat(),
        }
        with self._path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def all(self) -> list[dict[str, object]]:
        if not self._path.is_file():
            return []
        with self._path.open(encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]
