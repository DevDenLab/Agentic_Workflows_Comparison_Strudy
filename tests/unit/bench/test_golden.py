"""The golden set is data, but it is checked like code: shape, balance, consistency with policy."""

import re
import shutil
from collections import Counter
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from triage.bench.golden import GoldenCase, GoldenSet, Split, Subtype, load_golden_set
from triage.config import ConfigError, LoadedConfig

CASES_PER_SPLIT = 50
CASES_PER_ADVERSARIAL_SUBTYPE = 10
PREFIX = {Split.IN_DIST: "IND", Split.OOD: "OOD", Split.ADVERSARIAL: "ADV"}


@pytest.fixture(scope="module")
def golden(data_dir: Path) -> GoldenSet:
    return load_golden_set(data_dir / "golden")


# --- the shipped golden set -----------------------------------------------------


@pytest.mark.parametrize("split", list(Split))
def test_each_split_has_fifty_sequential_ids(golden: GoldenSet, split: Split) -> None:
    ids = sorted(case.id for case in golden.split(split))

    assert ids == [f"{PREFIX[split]}-{n:03d}" for n in range(1, CASES_PER_SPLIT + 1)]


def test_adversarial_subtypes_are_balanced(golden: GoldenSet) -> None:
    counts = Counter(case.subtype for case in golden.split(Split.ADVERSARIAL))

    assert counts == {
        subtype: CASES_PER_ADVERSARIAL_SUBTYPE
        for subtype in Subtype
        if subtype is not Subtype.STANDARD
    }


@pytest.mark.parametrize("split", [Split.IN_DIST, Split.OOD])
def test_every_category_appears_in_the_standard_splits(
    golden: GoldenSet, loaded_config: LoadedConfig, split: Split
) -> None:
    categories = {case.label.category for case in golden.split(split)}

    assert categories == loaded_config.taxonomy.category_ids


def test_labels_use_only_taxonomy_values(golden: GoldenSet, loaded_config: LoadedConfig) -> None:
    assert golden.violations(loaded_config.taxonomy) == []


def test_priority_follows_the_policy_matrix(golden: GoldenSet, config_dir: Path) -> None:
    """Guide section 4: priority = matrix[impact][urgency]."""
    policy = yaml.safe_load((config_dir / "priority_matrix.yaml").read_text(encoding="utf-8"))
    matrix = policy["matrix"]

    wrong = [
        f"{case.id}: {case.label.impact}/{case.label.urgency} -> {case.label.priority}"
        for case in golden.cases
        if case.label.determinable
        and matrix[case.label.impact][case.label.urgency] != case.label.priority
    ]

    assert wrong == []


def test_internal_senders_exist_in_the_cmdb(golden: GoldenSet, data_dir: Path) -> None:
    """Impact depends on the requester's CMDB department (guide I2), so senders must resolve."""
    seed = (data_dir / "cmdb" / "seed.sql").read_text(encoding="utf-8")
    known = set(re.findall(r"'([\w.]+@contoso\.example)'", seed))

    internal = {c.input.sender for c in golden.cases if c.input.sender.endswith("@contoso.example")}

    assert sorted(internal - known) == []


def test_standard_splits_only_have_auto_handling(golden: GoldenSet) -> None:
    escalations = [
        case.id
        for split in (Split.IN_DIST, Split.OOD)
        for case in golden.split(split)
        if case.label.handling != "auto"
    ]

    assert escalations == []


def test_no_ticket_body_is_duplicated(golden: GoldenSet) -> None:
    bodies = Counter(case.input.body.strip().lower() for case in golden.cases)

    assert [body for body, n in bodies.items() if n > 1] == []


# --- schema rules ---------------------------------------------------------------


def _case(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "ADV-001",
        "split": "adversarial",
        "subtype": "pii",
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
    return base | overrides


def _label(**overrides: object) -> dict[str, object]:
    label = _case()["label"]
    assert isinstance(label, dict)
    return {**label, **overrides}


def test_valid_case_is_accepted() -> None:
    assert GoldenCase.model_validate(_case()).label.determinable


def test_id_prefix_must_match_split() -> None:
    with pytest.raises(ValidationError, match="start with ADV-"):
        GoldenCase.model_validate(_case(id="IND-001"))


@pytest.mark.parametrize(
    ("split", "case_id", "subtype"),
    [("in_dist", "IND-001", "pii"), ("adversarial", "ADV-001", "standard")],
)
def test_subtype_must_suit_the_split(split: str, case_id: str, subtype: str) -> None:
    with pytest.raises(ValidationError, match="specific subtype"):
        GoldenCase.model_validate(_case(split=split, id=case_id, subtype=subtype))


def test_must_escalate_cases_need_escalate_handling() -> None:
    with pytest.raises(ValidationError, match="need handling: escalate"):
        GoldenCase.model_validate(_case(subtype="must_escalate"))


def test_labels_are_all_set_or_all_null() -> None:
    with pytest.raises(ValidationError, match="all be set or all null"):
        GoldenCase.model_validate(_case(label=_label(priority=None)))


def test_null_labels_need_escalation_and_the_ambiguous_subtype() -> None:
    nulls = {k: None for k in ("category", "impact", "urgency", "priority", "assignment_group")}

    with pytest.raises(ValidationError, match="needs handling: escalate"):
        GoldenCase.model_validate(_case(subtype="ambiguous", label=_label(**nulls)))
    with pytest.raises(ValidationError, match="only ambiguous cases"):
        GoldenCase.model_validate(_case(label=_label(**nulls, handling="escalate")))

    accepted = GoldenCase.model_validate(
        _case(subtype="ambiguous", label=_label(**nulls, handling="escalate"))
    )
    assert not accepted.label.determinable


def test_file_whose_split_does_not_match_its_name_is_rejected(
    data_dir: Path, tmp_path: Path
) -> None:
    golden_dir = tmp_path / "golden"
    shutil.copytree(data_dir / "golden", golden_dir)
    ood = golden_dir / "ood.yaml"
    ood.write_text(
        ood.read_text(encoding="utf-8").replace("split: ood", "split: in_dist"), encoding="utf-8"
    )

    with pytest.raises(ConfigError, match=r"ood\.yaml"):
        load_golden_set(golden_dir)
