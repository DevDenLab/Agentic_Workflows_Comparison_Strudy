from triage.observability.metrics import TriageMetrics


def test_instances_do_not_share_counts() -> None:
    first, second = TriageMetrics(), TriageMetrics()

    first.rule_misses.inc()

    assert first.registry.get_sample_value("triage_rule_misses_total") == 1
    assert second.registry.get_sample_value("triage_rule_misses_total") == 0


def test_labelled_counters_and_histogram_record_values() -> None:
    metrics = TriageMetrics()

    metrics.tickets.labels(pipeline="v1", outcome="auto_resolved", decided_by="rules").inc()
    metrics.rule_hits.labels(rule_id="R040").inc(2)
    metrics.latency.labels(pipeline="v1").observe(0.02)

    registry = metrics.registry
    labels = {"pipeline": "v1", "outcome": "auto_resolved", "decided_by": "rules"}
    assert registry.get_sample_value("triage_tickets_total", labels) == 1
    assert registry.get_sample_value("triage_rule_hits_total", {"rule_id": "R040"}) == 2
    assert registry.get_sample_value("triage_latency_seconds_count", {"pipeline": "v1"}) == 1


def test_exposition_is_prometheus_text() -> None:
    metrics = TriageMetrics()
    metrics.dead_letter_depth.set(3)

    text = metrics.exposition().decode("utf-8")

    assert "# TYPE triage_dead_letter_depth gauge" in text
    assert "triage_dead_letter_depth 3.0" in text
