from triage.v2.retrieval import SearchIndex


def _index() -> SearchIndex:
    return SearchIndex(
        [
            (
                "doc:vpn",
                "VPN drops repeatedly for remote users working from home",
                {"topic": "vpn"},
            ),
            (
                "doc:printer",
                "office printer toner cartridge replacement guide",
                {"topic": "printing"},
            ),
            ("doc:wifi", "wireless access point coverage gap in a hallway", {"topic": "wifi"}),
        ]
    )


def test_search_ranks_the_closest_document_first() -> None:
    hits = _index().search("my vpn keeps disconnecting", k=1)

    assert len(hits) == 1
    assert hits[0].doc_id == "doc:vpn"
    assert hits[0].metadata == {"topic": "vpn"}


def test_k_limits_the_result_count() -> None:
    hits = _index().search("network problem", k=2)

    assert len(hits) <= 2


def test_min_score_floor_excludes_weak_matches() -> None:
    hits = _index().search("completely unrelated query about lunch menus", min_score=0.5)

    assert hits == []


def test_empty_corpus_returns_nothing() -> None:
    assert SearchIndex([]).search("anything") == []


def test_scores_are_between_zero_and_one() -> None:
    hits = _index().search("vpn", k=3, min_score=0.0)

    assert all(0.0 <= hit.score <= 1.0 for hit in hits)
