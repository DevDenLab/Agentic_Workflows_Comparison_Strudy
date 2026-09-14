"""Prometheus metrics for the triage pipelines.

Each `TriageMetrics` owns its registry instead of using prometheus_client's global default, so tests
and benchmark runs never share counts. Derived numbers are PromQL over these series:

    rule match rate  = rate(triage_rule_hits_total) / (rate(triage_rule_hits_total) + rate(triage_rule_misses_total))
    p95 latency      = histogram_quantile(0.95, rate(triage_latency_seconds_bucket[5m]))
    DLQ depth        = triage_dead_letter_depth
"""  # noqa: E501

from collections.abc import Sequence

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

DEFAULT_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)


class TriageMetrics:
    def __init__(self, latency_buckets: Sequence[float] = DEFAULT_LATENCY_BUCKETS) -> None:
        self.registry = CollectorRegistry()
        self.tickets = Counter(
            "triage_tickets_total",
            "Tickets processed, by pipeline, outcome and who decided.",
            ["pipeline", "outcome", "decided_by"],
            registry=self.registry,
        )
        self.rule_hits = Counter(
            "triage_rule_hits_total",
            "Rule engine matches, by rule id.",
            ["rule_id"],
            registry=self.registry,
        )
        self.rule_misses = Counter(
            "triage_rule_misses_total", "Tickets no rule matched.", registry=self.registry
        )
        self.latency = Histogram(
            "triage_latency_seconds",
            "End-to-end triage latency.",
            ["pipeline"],
            buckets=latency_buckets,
            registry=self.registry,
        )
        self.itsm_attempts = Counter(
            "triage_itsm_attempts_total",
            "ITSM create-ticket attempts, retries included.",
            registry=self.registry,
        )
        self.dead_letter_depth = Gauge(
            "triage_dead_letter_depth",
            "ITSM requests waiting in the dead-letter queue.",
            registry=self.registry,
        )
        self.human_queue_depth = Gauge(
            "triage_human_queue_depth",
            "Tickets waiting for human triage.",
            registry=self.registry,
        )

    def exposition(self) -> bytes:
        """Prometheus text format, for a /metrics endpoint or a textfile collector."""
        return generate_latest(self.registry)
