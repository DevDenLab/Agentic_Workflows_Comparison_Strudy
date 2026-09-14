"""Step 4 — Extractor: pull identifiers out of ticket text with regular expressions."""

import re
from collections.abc import Iterable, Iterator

from triage.config import ConfigModel, RegexPattern
from triage.contracts import ExtractedFields


class ExtractorConfig(ConfigModel):
    employee_id: RegexPattern
    asset_tag: RegexPattern
    error_code: RegexPattern


class Extractor:
    def __init__(self, config: ExtractorConfig) -> None:
        self._employee_id = re.compile(config.employee_id, re.IGNORECASE)
        self._asset_tag = re.compile(config.asset_tag, re.IGNORECASE)
        self._error_code = re.compile(config.error_code, re.IGNORECASE)

    def extract(self, subject: str, text: str) -> ExtractedFields:
        haystack = f"{subject}\n{text}"
        return ExtractedFields(
            employee_ids=_unique(m.upper() for m in _matches(self._employee_id, haystack)),
            asset_tags=_unique(m.upper() for m in _matches(self._asset_tag, haystack)),
            error_codes=_unique(_matches(self._error_code, haystack)),
        )


def _matches(pattern: re.Pattern[str], text: str) -> Iterator[str]:
    return (match.group(0) for match in pattern.finditer(text))


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    """De-duplicate, keeping first-seen order."""
    return tuple(dict.fromkeys(values))
