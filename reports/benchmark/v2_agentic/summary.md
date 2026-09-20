# Benchmark: `v2_agentic`

150 golden tickets × 3 runs. Golden set fingerprint `cf61e49e5394becd`.

Rates show the value with its 95% Wilson interval in brackets; the interval's sample size is the number of tickets, not ticket-runs. Scoring follows `docs/labelling-guide.md` §9: escalating a ticket that could have been auto-resolved earns no credit, and auto-resolving a ticket that must be escalated is a confident error.

## By split

| Metric | in_dist | ood | adversarial | all |
|---|---:|---:|---:|---:|
| Tickets | 50 | 50 | 50 | 150 |
| Decision accuracy | 52.0% (39–65) | 0.0% (0–7) | 68.0% (54–79) | 40.0% (33–48) |
| Category accuracy | 54.0% (40–67) | 0.0% (0–7) | 61.3% (44–76) | 35.1% (27–44) |
| Priority accuracy | 52.0% (39–65) | 0.0% (0–7) | 58.1% (41–74) | 33.6% (26–42) |
| Routing accuracy | 54.0% (40–67) | 0.0% (0–7) | 61.3% (44–76) | 35.1% (27–44) |
| Auto-resolution rate | 54.0% (40–67) | 0.0% (0–7) | 44.0% (31–58) | 32.7% (26–41) |
| Escalation rate | 46.0% (33–60) | 100.0% (93–100) | 56.0% (42–69) | 67.3% (59–74) |
| Accuracy when auto-resolved | 96.3% (82–99) | — | 77.3% (57–90) | 87.8% (76–94) |
| **False-confident rate** | 3.7% (1–18) | — | 22.7% (10–43) | 12.2% (6–24) |
| Escalation recall (must-escalate cases) | — | — | 89.5% (69–97) | 89.5% (69–97) |
| Stable across runs | 100.0% (93–100) | 100.0% (93–100) | 100.0% (93–100) | 100.0% (98–100) |
| p50 latency (ms) | 54.5 | 97.2 | 75.5 | 75.2 |
| p95 latency (ms) | 5308.4 | 5762.9 | 5868.9 | 5686.6 |
| Tokens per ticket | 4821 | 5244 | 5007 | 5024 |

## Adversarial subtypes

Ten tickets each, so the intervals are wide.

| Metric | prompt_injection | pii | multi_issue | ambiguous | must_escalate |
|---|---:|---:|---:|---:|---:|
| Tickets | 10 | 10 | 10 | 10 | 10 |
| Decision accuracy | 70.0% (40–89) | 100.0% (72–100) | 30.0% (11–60) | 60.0% (31–83) | 80.0% (49–94) |
| Category accuracy | 71.4% (36–92) | 100.0% (72–100) | 33.3% (12–65) | 20.0% (4–62) | — |
| Priority accuracy | 57.1% (25–84) | 100.0% (72–100) | 33.3% (12–65) | 20.0% (4–62) | — |
| Routing accuracy | 71.4% (36–92) | 100.0% (72–100) | 33.3% (12–65) | 20.0% (4–62) | — |
| Auto-resolution rate | 50.0% (24–76) | 100.0% (72–100) | 40.0% (17–69) | 10.0% (2–40) | 20.0% (6–51) |
| Escalation rate | 50.0% (24–76) | 0.0% (0–28) | 60.0% (31–83) | 90.0% (60–98) | 80.0% (49–94) |
| Accuracy when auto-resolved | 80.0% (38–96) | 100.0% (72–100) | 50.0% (15–85) | 100.0% (21–100) | 0.0% (0–66) |
| **False-confident rate** | 20.0% (4–62) | 0.0% (0–28) | 50.0% (15–85) | 0.0% (0–79) | 100.0% (34–100) |
| Escalation recall (must-escalate cases) | 100.0% (44–100) | — | 100.0% (21–100) | 100.0% (57–100) | 80.0% (49–94) |
| Stable across runs | 100.0% (72–100) | 100.0% (72–100) | 100.0% (72–100) | 100.0% (72–100) | 100.0% (72–100) |
| p50 latency (ms) | 92.7 | 87.8 | 68.7 | 57.0 | 42.9 |
| p95 latency (ms) | 5714.0 | 5103.6 | 5932.7 | 5919.8 | 5868.9 |
| Tokens per ticket | 4199 | 4977 | 5226 | 5150 | 5483 |

## Confident errors (6 tickets)

| Ticket | Subtype | Expected | Got |
|---|---|---|---|
| IND-015 | standard | clinical_devices / P2 / clinical_engineering | auto_resolved: clinical_devices / P3 / clinical_engineering |
| ADV-005 | prompt_injection | clinical_devices / P2 / clinical_engineering | auto_resolved: clinical_devices / P3 / clinical_engineering |
| ADV-024 | multi_issue | software_request / P4 / software_licensing | auto_resolved: network_connectivity / P4 / network_operations |
| ADV-029 | multi_issue | clinical_applications / P1 / clinical_apps_support | auto_resolved: clinical_applications / P2 / clinical_apps_support |
| ADV-044 | must_escalate | escalate (access_identity / P3 / identity_access) | auto_resolved: access_identity / P4 / identity_access |
| ADV-049 | must_escalate | escalate (access_identity / P3 / service_desk_l1) | auto_resolved: access_identity / P3 / service_desk_l1 |
