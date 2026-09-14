import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from triage.config import ConfigError, LoadedConfig
from triage.v1.priority_matrix import Level
from triage.v1.rule_engine import RuleEngine, RuleMatch, RuleSet
from triage.v1.settings import V1Config, load_v1_config


@pytest.fixture(scope="module")
def engine(v1_config: V1Config) -> RuleEngine:
    return RuleEngine(v1_config.rules)


def _rule_set(**rule: object) -> RuleSet:
    base: dict[str, object] = {
        "id": "R001",
        "description": "test",
        "category": "access_identity",
        "urgency": "medium",
        "any_of": ["password"],
    }
    return RuleSet.model_validate({"version": "1.0.0", "rules": [base | rule]})


@pytest.mark.parametrize(
    ("subject", "text", "rule_id"),
    [
        ("Suspicious email", "It asks me to confirm my password, looks like phishing", "R001"),
        ("", "I am locked out of my account", "R010"),
        ("EMR password reset", "Need a password reset for the EMR", "R020"),
        ("", "Authenticator app keeps rejecting the verification code", "R011"),
        ("Copier", "The copier on 2 East won't scan to email", "R030"),
        ("", "Barcode scanner on the med cart won't read wristbands", "R031"),
        ("VPN", "VPN drops every 10 minutes when I work from home", "R040"),
        ("", "Outlook keeps asking for my credentials", "R050"),
        ("", "Paper jam in the printer by the nursing station", "R060"),
        ("", "My laptop shows a blue screen", "R070"),
        ("", "Please install Visio", "R080"),
    ],
)
def test_shipped_rules_classify_the_phrasings_they_were_written_for(
    engine: RuleEngine, subject: str, text: str, rule_id: str
) -> None:
    match = engine.match(subject, text)

    assert match is not None
    assert match.rule_id == rule_id


def test_match_reports_rule_category_urgency_and_phrase(engine: RuleEngine) -> None:
    assert engine.match("", "VPN is down") == RuleMatch(
        rule_id="R040",
        category="network_connectivity",
        urgency=Level.MEDIUM,
        matched_phrase="vpn",
    )


def test_first_matching_rule_wins(engine: RuleEngine) -> None:
    match = engine.match("", "I clicked a phishing link in Outlook")

    assert match is not None
    assert match.rule_id == "R001"


def test_phrases_match_whole_words_only(engine: RuleEngine) -> None:
    assert engine.match("", "The monitoring dashboard is slow") is None


def test_a_new_phrasing_is_a_miss(engine: RuleEngine) -> None:
    """The limit v2 exists to address: nobody wrote a rule for this wording."""
    assert engine.match("", "My computer screen went black and it beeps three times") is None


def test_none_of_blocks_a_rule() -> None:
    engine = RuleEngine(_rule_set(none_of=["emr"]))

    assert engine.match("", "password expired") is not None
    assert engine.match("", "EMR password expired") is None


def test_duplicate_rule_ids_are_rejected() -> None:
    rule = {
        "id": "R001",
        "description": "d",
        "category": "printing",
        "urgency": "low",
        "any_of": ["printer"],
    }
    with pytest.raises(ValidationError, match="duplicate rule ids"):
        RuleSet.model_validate({"version": "1.0.0", "rules": [rule, rule]})


def test_unknown_category_is_reported(loaded_config: LoadedConfig) -> None:
    violations = _rule_set(category="hardware").violations(loaded_config.taxonomy)

    assert violations == ["rule R001: category 'hardware' is not in the taxonomy"]


def test_loading_fails_when_rules_do_not_match_taxonomy(
    config_dir: Path, tmp_path: Path, loaded_config: LoadedConfig
) -> None:
    copy = tmp_path / "config"
    shutil.copytree(config_dir, copy)
    rules = copy / "rules.yaml"
    rules.write_text(
        rules.read_text(encoding="utf-8").replace("category: printing", "category: print"),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="does not match taxonomy"):
        load_v1_config(copy, loaded_config.taxonomy)
