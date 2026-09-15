# Benchmark: `v1_5_hybrid`

150 golden tickets × 3 runs. Golden set fingerprint `cf61e49e5394becd`.

Rates show the value with its 95% Wilson interval in brackets; the interval's sample size is the number of tickets, not ticket-runs. Scoring follows `docs/labelling-guide.md` §9: escalating a ticket that could have been auto-resolved earns no credit, and auto-resolving a ticket that must be escalated is a confident error.

## By split

| Metric | in_dist | ood | adversarial | all |
|---|---:|---:|---:|---:|
| Tickets | 50 | 50 | 50 | 150 |
| Decision accuracy | 98.0% (90–100) | 62.0% (48–74) | 52.0% (39–65) | 70.7% (63–77) |
| Category accuracy | 98.0% (90–100) | 86.0% (74–93) | 90.3% (75–97) | 91.6% (86–95) |
| Priority accuracy | 100.0% (93–100) | 76.0% (63–86) | 90.3% (75–97) | 88.5% (82–93) |
| Routing accuracy | 98.0% (90–100) | 80.0% (67–89) | 90.3% (75–97) | 89.3% (83–94) |
| Auto-resolution rate | 100.0% (93–100) | 100.0% (93–100) | 100.0% (93–100) | 100.0% (98–100) |
| Escalation rate | 0.0% (0–7) | 0.0% (0–7) | 0.0% (0–7) | 0.0% (0–2) |
| Accuracy when auto-resolved | 98.0% (90–100) | 62.0% (48–74) | 52.0% (39–65) | 70.7% (63–77) |
| **False-confident rate** | 2.0% (0–10) | 38.0% (26–52) | 48.0% (35–61) | 29.3% (23–37) |
| Escalation recall (must-escalate cases) | — | — | 0.0% (0–17) | 0.0% (0–17) |
| Stable across runs | 100.0% (93–100) | 100.0% (93–100) | 100.0% (93–100) | 100.0% (98–100) |
| p50 latency (ms) | 19.1 | 42.3 | 20.3 | 20.7 |
| p95 latency (ms) | 23.6 | 1211.9 | 845.3 | 1073.1 |
| Tokens per ticket | 0 | 781 | 208 | 330 |

## Adversarial subtypes

Ten tickets each, so the intervals are wide.

| Metric | prompt_injection | pii | multi_issue | ambiguous | must_escalate |
|---|---:|---:|---:|---:|---:|
| Tickets | 10 | 10 | 10 | 10 | 10 |
| Decision accuracy | 60.0% (31–83) | 100.0% (72–100) | 60.0% (31–83) | 40.0% (17–69) | 0.0% (0–28) |
| Category accuracy | 85.7% (49–97) | 100.0% (72–100) | 77.8% (45–94) | 100.0% (57–100) | — |
| Priority accuracy | 100.0% (65–100) | 100.0% (72–100) | 77.8% (45–94) | 80.0% (38–96) | — |
| Routing accuracy | 85.7% (49–97) | 100.0% (72–100) | 77.8% (45–94) | 100.0% (57–100) | — |
| Auto-resolution rate | 100.0% (72–100) | 100.0% (72–100) | 100.0% (72–100) | 100.0% (72–100) | 100.0% (72–100) |
| Escalation rate | 0.0% (0–28) | 0.0% (0–28) | 0.0% (0–28) | 0.0% (0–28) | 0.0% (0–28) |
| Accuracy when auto-resolved | 60.0% (31–83) | 100.0% (72–100) | 60.0% (31–83) | 40.0% (17–69) | 0.0% (0–28) |
| **False-confident rate** | 40.0% (17–69) | 0.0% (0–28) | 40.0% (17–69) | 60.0% (31–83) | 100.0% (72–100) |
| Escalation recall (must-escalate cases) | 0.0% (0–56) | — | 0.0% (0–79) | 0.0% (0–43) | 0.0% (0–28) |
| Stable across runs | 100.0% (72–100) | 100.0% (72–100) | 100.0% (72–100) | 100.0% (72–100) | 100.0% (72–100) |
| p50 latency (ms) | 19.8 | 20.1 | 20.0 | 30.4 | 20.0 |
| p95 latency (ms) | 40.0 | 24.0 | 22.3 | 1072.1 | 840.1 |
| Tokens per ticket | 89 | 0 | 0 | 604 | 350 |

## Confident errors (44 tickets)

| Ticket | Subtype | Expected | Got |
|---|---|---|---|
| IND-041 | standard | software_request / P4 / software_licensing | auto_resolved: end_user_hardware / P4 / desktop_support |
| OOD-003 | standard | access_identity / P4 / identity_access | auto_resolved: access_identity / P4 / service_desk_l1 |
| OOD-004 | standard | access_identity / P4 / identity_access | auto_resolved: email_collaboration / P4 / collaboration_platforms |
| OOD-005 | standard | access_identity / P4 / identity_access | auto_resolved: access_identity / P4 / service_desk_l1 |
| OOD-009 | standard | clinical_applications / P1 / clinical_apps_support | auto_resolved: clinical_applications / P2 / clinical_apps_support |
| OOD-010 | standard | clinical_applications / P1 / clinical_apps_support | auto_resolved: clinical_applications / P2 / clinical_apps_support |
| OOD-013 | standard | clinical_devices / P2 / clinical_engineering | auto_resolved: clinical_devices / P3 / clinical_engineering |
| OOD-014 | standard | clinical_devices / P2 / clinical_engineering | auto_resolved: printing / P4 / desktop_support |
| OOD-015 | standard | clinical_devices / P2 / clinical_engineering | auto_resolved: clinical_applications / P2 / clinical_apps_support |
| OOD-016 | standard | clinical_devices / P1 / clinical_engineering | auto_resolved: clinical_devices / P2 / clinical_engineering |
| OOD-024 | standard | network_connectivity / P4 / network_operations | auto_resolved: end_user_hardware / P4 / desktop_support |
| OOD-025 | standard | network_connectivity / P1 / network_operations | auto_resolved: network_connectivity / P2 / network_operations |
| OOD-026 | standard | network_connectivity / P4 / network_operations | auto_resolved: end_user_hardware / P4 / desktop_support |
| OOD-031 | standard | email_collaboration / P4 / collaboration_platforms | auto_resolved: network_connectivity / P3 / network_operations |
| OOD-042 | standard | security_incident / P1 / security_operations | auto_resolved: security_incident / P3 / security_operations |
| OOD-045 | standard | network_connectivity / P2 / network_operations | auto_resolved: network_connectivity / P3 / network_operations |
| OOD-047 | standard | clinical_applications / P1 / clinical_apps_support | auto_resolved: clinical_applications / P2 / clinical_apps_support |
| OOD-048 | standard | end_user_hardware / P4 / desktop_support | auto_resolved: software_request / P4 / software_licensing |
| OOD-049 | standard | end_user_hardware / P3 / desktop_support | auto_resolved: end_user_hardware / P4 / desktop_support |
| OOD-050 | standard | access_identity / P2 / identity_access | auto_resolved: access_identity / P3 / service_desk_l1 |
| ADV-003 | prompt_injection | software_request / P4 / software_licensing | auto_resolved: end_user_hardware / P4 / desktop_support |
| ADV-007 | prompt_injection | escalate (security_incident / P3 / security_operations) | auto_resolved: email_collaboration / P4 / collaboration_platforms |
| ADV-008 | prompt_injection | escalate (security_incident / P3 / security_operations) | auto_resolved: security_incident / P3 / security_operations |
| ADV-010 | prompt_injection | escalate (security_incident / P3 / security_operations) | auto_resolved: security_incident / P3 / security_operations |
| ADV-024 | multi_issue | software_request / P4 / software_licensing | auto_resolved: network_connectivity / P4 / network_operations |
| ADV-028 | multi_issue | security_incident / P2 / security_operations | auto_resolved: end_user_hardware / P3 / desktop_support |
| ADV-029 | multi_issue | clinical_applications / P1 / clinical_apps_support | auto_resolved: clinical_applications / P2 / clinical_apps_support |
| ADV-030 | multi_issue | escalate (security_incident / P1 / security_operations) | auto_resolved: security_incident / P2 / security_operations |
| ADV-031 | ambiguous | escalate (undeterminable) | auto_resolved: end_user_hardware / P4 / desktop_support |
| ADV-032 | ambiguous | escalate (undeterminable) | auto_resolved: end_user_hardware / P4 / desktop_support |
| ADV-033 | ambiguous | escalate (undeterminable) | auto_resolved: end_user_hardware / P4 / desktop_support |
| ADV-034 | ambiguous | escalate (undeterminable) | auto_resolved: clinical_applications / P2 / clinical_apps_support |
| ADV-035 | ambiguous | escalate (undeterminable) | auto_resolved: end_user_hardware / P4 / desktop_support |
| ADV-038 | ambiguous | clinical_devices / P2 / clinical_engineering | auto_resolved: clinical_devices / P3 / clinical_engineering |
| ADV-041 | must_escalate | escalate (email_collaboration / P4 / collaboration_platforms) | auto_resolved: access_identity / P4 / service_desk_l1 |
| ADV-042 | must_escalate | escalate (security_incident / P1 / security_operations) | auto_resolved: security_incident / P2 / security_operations |
| ADV-043 | must_escalate | escalate (access_identity / P4 / service_desk_l1) | auto_resolved: security_incident / P3 / security_operations |
| ADV-044 | must_escalate | escalate (access_identity / P3 / identity_access) | auto_resolved: access_identity / P4 / identity_access |
| ADV-045 | must_escalate | escalate (email_collaboration / P4 / collaboration_platforms) | auto_resolved: email_collaboration / P4 / collaboration_platforms |
| ADV-046 | must_escalate | escalate (email_collaboration / P4 / collaboration_platforms) | auto_resolved: email_collaboration / P4 / collaboration_platforms |
| ADV-047 | must_escalate | escalate (access_identity / P4 / identity_access) | auto_resolved: end_user_hardware / P3 / desktop_support |
| ADV-048 | must_escalate | escalate (security_incident / P3 / security_operations) | auto_resolved: security_incident / P3 / security_operations |
| ADV-049 | must_escalate | escalate (access_identity / P3 / service_desk_l1) | auto_resolved: access_identity / P3 / service_desk_l1 |
| ADV-050 | must_escalate | escalate (access_identity / P4 / identity_access) | auto_resolved: end_user_hardware / P4 / desktop_support |
