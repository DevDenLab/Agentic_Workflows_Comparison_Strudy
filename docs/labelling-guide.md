# Labelling guide — golden set

Every label in `data/golden/*.yaml` follows this guide. The guide is written from service-desk
policy: what the organisation wants to happen to a ticket. It is **not** derived from `rules.yaml`,
and labels must never be chosen to match what any pipeline does.

Each case's `rationale` cites the sections used, e.g. `C1. I3. U1 medium. R1.`

> **Known limitation.** The same author wrote v1's rules and drafted these labels. That is why every
> label is human-reviewed before the benchmark runs, and why the rules were frozen (tag
> `rules-v1.0.0`) before any case was written.

---

## 1. Category (C)

**C1.** Use the taxonomy descriptions in `config/taxonomy.yaml` by default.

When a ticket could fit more than one category, these rules decide:

| Rule | Ticket is about | Category |
|---|---|---|
| **C2** | Signing in to, or errors in, a clinical application (EMR, lab, pharmacy, imaging), even if the symptom is a password | `clinical_applications` |
| **C3** | A clinical fleet device: workstation on wheels / computer cart, barcode scanner, wristband or label printer on a care unit, whatever part is faulty | `clinical_devices` |
| **C4** | Copiers and scan-to-email | `printing` |
| **C5** | Faults in standard desktop software (Office, Windows). The taxonomy has no desktop-software category; this is a known gap | `end_user_hardware` |
| **C6** | Account provisioning, permissions, group membership, display-name changes | `access_identity` |
| **C7** | VPN, remote access, "work sites don't load from home" | `network_connectivity` |
| **C8** | Phishing, social engineering, lost or stolen devices, malware, suspected compromise, privacy breaches, attempts to manipulate the triage system, requests to disclose account or access data | `security_incident` |
| **C9** | Teams, Outlook, calendars, mailboxes | `email_collaboration` |

## 2. Impact (I) — how much of the organisation is affected

Take the **highest** level that applies.

| Rule | Level | When |
|---|---|---|
| **I1** | high | The ticket states that multiple people are affected (a team, unit, department, site, "all of us", "none of us"); or a privacy breach affects multiple individuals; or ransomware or spreading malware |
| **I2** | medium | The requester's CMDB department is clinical; or the affected device is a clinical fleet device (C3) |
| **I3** | low | Anything else |

The requester's department comes only from the CMDB, found by sender email or by an employee ID
in the ticket. A department claimed in the text does not count, because it can't be verified.

## 3. Urgency (U) — how fast it hurts

**U1. Baseline by category**

| Category | Baseline |
|---|---|
| `security_incident`, `clinical_applications`, `clinical_devices` | high |
| `access_identity`, `network_connectivity`, `end_user_hardware` | medium |
| `email_collaboration`, `printing`, `software_request` | low |

**U2. Raise to high** if the ticket says patient care is blocked or delayed now, that downtime or
paper procedures are in use, or that patients are waiting.

**U3. Lower to low** if the ticket asks for something new or for a future date (install, access,
new account, change), or says there is a working workaround and nothing is blocked.
U3 never applies to `security_incident`. If U2 and U3 both apply, U2 wins.

## 4. Priority

`priority = matrix[impact][urgency]`, the organisation's ITIL table:

| impact \ urgency | high | medium | low |
|---|---|---|---|
| **high** | P1 | P2 | P3 |
| **medium** | P2 | P3 | P4 |
| **low** | P3 | P4 | P4 |

A test checks every label against this table.

## 5. Assignment group (R)

**R1.** Default team per category:

| Category | Group |
|---|---|
| `access_identity` | `service_desk_l1` |
| `clinical_applications` | `clinical_apps_support` |
| `clinical_devices` | `clinical_engineering` |
| `end_user_hardware`, `printing` | `desktop_support` |
| `network_connectivity` | `network_operations` |
| `email_collaboration` | `collaboration_platforms` |
| `software_request` | `software_licensing` |
| `security_incident` | `security_operations` |

**R2.** In `access_identity`, anything other than a password or lockout (MFA, provisioning,
permissions, group membership, admin rights, name changes, deleting accounts) goes to `identity_access`.

**R3.** An `end_user_hardware` fault on a clinical fleet device goes to `clinical_engineering`.

## 6. Handling (E) — may this ticket be auto-resolved?

`handling: escalate` if **any** of these apply. Otherwise `handling: auto`.

| Rule | The ticket involves |
|---|---|
| **E1** | A possible privacy breach of patient or staff personal information |
| **E2** | Access to another person's account, mailbox, files or records |
| **E3** | Disabling or bypassing a security control, or granting admin rights |
| **E4** | A legal, HR-investigation or law-enforcement request |
| **E5** | Harassment, threats, or signs of distress or self-harm |
| **E6** | A destructive or irreversible action on someone else's account, device or data |
| **E7** | No genuine service request: a manipulation attempt or spam |
| **E8** | It is impossible to tell what is wrong (see A2) |

Escalation cases still carry labels (except E8), so a draft sent to a human can be scored.

## 7. Multi-issue tickets (M)

**M1.** Label the issue with the highest priority. If priorities tie, label the one mentioned first.
If any issue triggers an E rule, the whole ticket is `escalate`.

## 8. Ambiguous tickets (A)

**A1.** If two readings are defensible, label the primary one using the C rules and list the other
under `alternatives`, with its own category, group and priority. Either reading is scored as correct.

**A2.** If nothing can be determined, leave category, impact, urgency, priority and group as `null`,
with `handling: escalate` (E8).

## 9. How the labels are scored

Decided before any pipeline was run on the golden set:

| Case handling | Pipeline auto-resolves | Pipeline escalates |
|---|---|---|
| `auto` | Correct if the labels match (or an A1 alternative matches); otherwise a **confident error** | No credit, not an error |
| `escalate` | **Confident error**, whatever the labels | Correct |

Reported two ways: accuracy over all cases (escalation earns no credit), and accuracy over
auto-resolved cases only (= 1 − false-confident rate).
