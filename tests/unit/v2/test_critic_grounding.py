"""The code-level half of the critic (9a): citations_are_grounded."""

from triage.v2.critic import citations_are_grounded


def test_every_citation_known_is_grounded() -> None:
    grounded, unknown = citations_are_grounded(
        ("rule:R040", "kb:network#vpn"), frozenset({"rule:R040", "kb:network#vpn"})
    )

    assert grounded
    assert unknown == ()


def test_an_unretrieved_citation_is_not_grounded() -> None:
    grounded, unknown = citations_are_grounded(("kb:fabricated#section",), frozenset({"rule:R040"}))

    assert not grounded
    assert unknown == ("kb:fabricated#section",)


def test_no_citations_is_vacuously_grounded() -> None:
    grounded, unknown = citations_are_grounded((), frozenset({"rule:R040"}))

    assert grounded
    assert unknown == ()


def test_only_the_unknown_ones_are_reported() -> None:
    _, unknown = citations_are_grounded(("rule:R040", "kb:fake#x"), frozenset({"rule:R040"}))

    assert unknown == ("kb:fake#x",)
