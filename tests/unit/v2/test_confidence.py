"""compute_confidence and may_auto_resolve are pure functions, pinned case by case."""

import pytest

from triage.contracts import Priority
from triage.v2.confidence import (
    ConfidenceConfig,
    ConfidenceSignals,
    compute_confidence,
    may_auto_resolve,
)

CONFIG = ConfidenceConfig(threshold=0.55, high_blast_radius_categories=("security_incident",))


def _signals(**overrides: object) -> ConfidenceSignals:
    base: dict[str, object] = {
        "critic_grounded": True,
        "apply_rules_agreement": None,
        "retrieval_strength": 0.0,
        "repair_attempts": 0,
    }
    return ConfidenceSignals(**(base | overrides))  # type: ignore[arg-type]


def test_ungrounded_is_always_zero_regardless_of_other_signals() -> None:
    signals = _signals(critic_grounded=False, apply_rules_agreement=True, retrieval_strength=1.0)

    assert compute_confidence(signals) == 0.0


@pytest.mark.parametrize(
    ("agreement", "expected_base"),
    [(True, 0.6), (False, 0.1), (None, 0.3)],
)
def test_apply_rules_agreement_sets_the_base_score(
    agreement: bool | None, expected_base: float
) -> None:
    score = compute_confidence(_signals(apply_rules_agreement=agreement))

    assert score == pytest.approx(expected_base)


def test_retrieval_strength_adds_up_to_035() -> None:
    low = compute_confidence(_signals(retrieval_strength=0.0))
    high = compute_confidence(_signals(retrieval_strength=1.0))

    assert high - low == pytest.approx(0.35)


def test_each_repair_attempt_costs_01() -> None:
    none = compute_confidence(_signals(repair_attempts=0))
    two = compute_confidence(_signals(repair_attempts=2))

    assert none - two == pytest.approx(0.2)


def test_score_is_clamped_to_zero_not_negative() -> None:
    assert compute_confidence(_signals(apply_rules_agreement=False, repair_attempts=5)) == 0.0


def test_score_never_exceeds_one_even_with_every_positive_signal_maxed() -> None:
    # 0.6 (agreement) + 0.35 (retrieval) = 0.95: the formula's own ceiling, well under 1.0 already,
    # confirming clamping isn't hiding a bug that would let repairs push a maxed score over 1.0.
    maxed = compute_confidence(
        _signals(apply_rules_agreement=True, retrieval_strength=1.0, repair_attempts=0)
    )
    assert maxed == pytest.approx(0.95)
    assert compute_confidence(_signals(apply_rules_agreement=True, retrieval_strength=1.0)) <= 1.0


def test_gate_passes_at_or_above_threshold() -> None:
    assert may_auto_resolve(0.55, "printing", Priority.P4, CONFIG)
    assert not may_auto_resolve(0.54, "printing", Priority.P4, CONFIG)


def test_high_blast_radius_category_never_auto_resolves() -> None:
    assert not may_auto_resolve(1.0, "security_incident", Priority.P4, CONFIG)


def test_p1_never_auto_resolves_regardless_of_category() -> None:
    assert not may_auto_resolve(1.0, "printing", Priority.P1, CONFIG)
