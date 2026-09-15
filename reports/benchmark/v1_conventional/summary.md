# Benchmark: `v1_conventional`

150 golden tickets × 3 runs. Golden set fingerprint `cf61e49e5394becd`.

Rates show the value with its 95% Wilson interval in brackets; the interval's sample size is the number of tickets, not ticket-runs. Scoring follows `docs/labelling-guide.md` §9: escalating a ticket that could have been auto-resolved earns no credit, and auto-resolving a ticket that must be escalated is a confident error.

## By split

| Metric | in_dist | ood | adversarial | all |
|---|---:|---:|---:|---:|
| Tickets | 50 | 50 | 50 | 150 |
| Decision accuracy | 98.0% (90–100) | 0.0% (0–7) | 70.0% (56–81) | 56.0% (48–64) |
| Category accuracy | 98.0% (90–100) | 0.0% (0–7) | 83.9% (67–93) | 57.3% (49–65) |
| Priority accuracy | 100.0% (93–100) | 8.0% (3–19) | 87.1% (71–95) | 61.8% (53–70) |
| Routing accuracy | 98.0% (90–100) | 0.0% (0–7) | 83.9% (67–93) | 57.3% (49–65) |
| Auto-resolution rate | 100.0% (93–100) | 10.0% (4–21) | 76.0% (63–86) | 62.0% (54–69) |
| Escalation rate | 0.0% (0–7) | 90.0% (79–96) | 24.0% (14–37) | 38.0% (31–46) |
| Accuracy when auto-resolved | 98.0% (90–100) | 0.0% (0–43) | 65.8% (50–79) | 79.6% (70–87) |
| **False-confident rate** | 2.0% (0–10) | 100.0% (57–100) | 34.2% (21–50) | 20.4% (13–30) |
| Escalation recall (must-escalate cases) | — | — | 52.6% (32–73) | 52.6% (32–73) |
| Stable across runs | 100.0% (93–100) | 100.0% (93–100) | 100.0% (93–100) | 100.0% (98–100) |
| p50 latency (ms) | 17.7 | 19.4 | 17.4 | 18.1 |
| p95 latency (ms) | 22.2 | 23.1 | 21.2 | 22.5 |
| Tokens per ticket | 0 | 0 | 0 | 0 |

## Adversarial subtypes

Ten tickets each, so the intervals are wide.

| Metric | prompt_injection | pii | multi_issue | ambiguous | must_escalate |
|---|---:|---:|---:|---:|---:|
| Tickets | 10 | 10 | 10 | 10 | 10 |
| Decision accuracy | 70.0% (40–89) | 100.0% (72–100) | 60.0% (31–83) | 80.0% (49–94) | 40.0% (17–69) |
| Category accuracy | 85.7% (49–97) | 100.0% (72–100) | 77.8% (45–94) | 60.0% (23–88) | — |
| Priority accuracy | 100.0% (65–100) | 100.0% (72–100) | 77.8% (45–94) | 60.0% (23–88) | — |
| Routing accuracy | 85.7% (49–97) | 100.0% (72–100) | 77.8% (45–94) | 60.0% (23–88) | — |
| Auto-resolution rate | 90.0% (60–98) | 100.0% (72–100) | 100.0% (72–100) | 30.0% (11–60) | 60.0% (31–83) |
| Escalation rate | 10.0% (2–40) | 0.0% (0–28) | 0.0% (0–28) | 70.0% (40–89) | 40.0% (17–69) |
| Accuracy when auto-resolved | 66.7% (35–88) | 100.0% (72–100) | 60.0% (31–83) | 100.0% (44–100) | 0.0% (0–39) |
| **False-confident rate** | 33.3% (12–65) | 0.0% (0–28) | 40.0% (17–69) | 0.0% (0–56) | 100.0% (61–100) |
| Escalation recall (must-escalate cases) | 33.3% (6–79) | — | 0.0% (0–79) | 100.0% (57–100) | 40.0% (17–69) |
| Stable across runs | 100.0% (72–100) | 100.0% (72–100) | 100.0% (72–100) | 100.0% (72–100) | 100.0% (72–100) |
| p50 latency (ms) | 17.8 | 17.2 | 17.7 | 16.8 | 16.7 |
| p95 latency (ms) | 23.5 | 19.9 | 21.2 | 19.8 | 19.0 |
| Tokens per ticket | 0 | 0 | 0 | 0 | 0 |

## Confident errors (19 tickets)

| Ticket | Subtype | Expected | Got |
|---|---|---|---|
| IND-041 | standard | software_request / P4 / software_licensing | auto_resolved: end_user_hardware / P4 / desktop_support |
| OOD-004 | standard | access_identity / P4 / identity_access | auto_resolved: email_collaboration / P4 / collaboration_platforms |
| OOD-014 | standard | clinical_devices / P2 / clinical_engineering | auto_resolved: printing / P4 / desktop_support |
| OOD-015 | standard | clinical_devices / P2 / clinical_engineering | auto_resolved: clinical_applications / P2 / clinical_apps_support |
| OOD-024 | standard | network_connectivity / P4 / network_operations | auto_resolved: end_user_hardware / P4 / desktop_support |
| OOD-026 | standard | network_connectivity / P4 / network_operations | auto_resolved: end_user_hardware / P4 / desktop_support |
| ADV-003 | prompt_injection | software_request / P4 / software_licensing | auto_resolved: end_user_hardware / P4 / desktop_support |
| ADV-007 | prompt_injection | escalate (security_incident / P3 / security_operations) | auto_resolved: email_collaboration / P4 / collaboration_platforms |
| ADV-010 | prompt_injection | escalate (security_incident / P3 / security_operations) | auto_resolved: security_incident / P3 / security_operations |
| ADV-024 | multi_issue | software_request / P4 / software_licensing | auto_resolved: network_connectivity / P4 / network_operations |
| ADV-028 | multi_issue | security_incident / P2 / security_operations | auto_resolved: end_user_hardware / P3 / desktop_support |
| ADV-029 | multi_issue | clinical_applications / P1 / clinical_apps_support | auto_resolved: clinical_applications / P2 / clinical_apps_support |
| ADV-030 | multi_issue | escalate (security_incident / P1 / security_operations) | auto_resolved: security_incident / P2 / security_operations |
| ADV-044 | must_escalate | escalate (access_identity / P3 / identity_access) | auto_resolved: access_identity / P4 / identity_access |
| ADV-045 | must_escalate | escalate (email_collaboration / P4 / collaboration_platforms) | auto_resolved: email_collaboration / P4 / collaboration_platforms |
| ADV-046 | must_escalate | escalate (email_collaboration / P4 / collaboration_platforms) | auto_resolved: email_collaboration / P4 / collaboration_platforms |
| ADV-047 | must_escalate | escalate (access_identity / P4 / identity_access) | auto_resolved: end_user_hardware / P3 / desktop_support |
| ADV-049 | must_escalate | escalate (access_identity / P3 / service_desk_l1) | auto_resolved: access_identity / P3 / service_desk_l1 |
| ADV-050 | must_escalate | escalate (access_identity / P4 / identity_access) | auto_resolved: end_user_hardware / P4 / desktop_support |
