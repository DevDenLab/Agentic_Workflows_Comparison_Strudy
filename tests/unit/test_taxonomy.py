import pytest
from pydantic import ValidationError

from triage.config import LoadedConfig
from triage.contracts import Taxonomy, TriageDecision


def _decision(category: str, group: str) -> TriageDecision:
    return TriageDecision(
        category=category,
        priority="P3",  # type: ignore[arg-type]
        assignment_group=group,
        draft_response="ack",
        confidence=1.0,
    )


def test_shipped_taxonomy_accepts_its_own_values(loaded_config: LoadedConfig) -> None:
    taxonomy = loaded_config.taxonomy
    for category in taxonomy.category_ids:
        for group in taxonomy.group_ids:
            assert taxonomy.violations(_decision(category, group)) == []


def test_violations_name_the_bad_value_and_list_allowed_ones(loaded_config: LoadedConfig) -> None:
    problems = loaded_config.taxonomy.violations(_decision("hardware", "network_operations"))

    assert len(problems) == 1
    assert "'hardware'" in problems[0]
    assert "end_user_hardware" in problems[0]


def test_both_fields_reported_when_both_are_wrong(loaded_config: LoadedConfig) -> None:
    assert len(loaded_config.taxonomy.violations(_decision("hardware", "helpdesk"))) == 2


def test_duplicate_ids_are_rejected() -> None:
    entry = {"id": "printing", "description": "Printers"}
    with pytest.raises(ValidationError, match="duplicate ids"):
        Taxonomy.model_validate(
            {
                "version": "1.0.0",
                "categories": [entry, entry],
                "assignment_groups": [{"id": "desktop_support", "description": "Desk"}],
            }
        )
