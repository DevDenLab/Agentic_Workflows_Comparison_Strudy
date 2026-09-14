# How a ticket flows through each pipeline

All three pipelines take the same `InboundMessage` and return the same `TriageResult`.
What changes is **who decides what happens next**: code, or the model.

---

## v1 — Conventional automation

Every arrow is fixed in code. Same input, same output, every time.

```
1) Intake            email (.eml) or web form arrives → InboundMessage
      ↓
2) Queue & Dedupe    message-id seen before? → DUPLICATE, stop
      ↓
3) Parser            strip MIME, HTML, signature, quoted replies → clean text
      ↓
4) Extractor         regex pulls employee ID, asset tag, error code
      ↓
5) Validate          build Ticket (Pydantic). Invalid? → 12) Human Triage Queue
      ↓
6) CMDB Lookup       SQL: employee → department → services; asset → service criticality
      ↓
7) Rule Engine       ordered keyword rules from rules.yaml, first match wins → category + urgency
      ↓              no rule matched? → 12) Human Triage Queue
8) Priority Matrix   impact (from CMDB criticality) × urgency (from rule) → P1–P4
      ↓
9) SLA Calculator    priority + received time + business hours + holidays → due time
      ↓
10) Routing Table    category → assignment group
      ↓
11) Responder        Jinja2 template for the category → first reply
      ↓
12) ITSM Write       create ticket with idempotency key
                     fails → retry with exponential backoff → still failing → dead-letter queue
      ↓
    AUTO_RESOLVED    routed, SLA clock running

12) Human Triage Queue   raw ticket, no decision, reason recorded → HUMAN_REVIEW
```

**Weak spot:** step 7. The rules only cover phrasings someone wrote down. A new phrasing means
a `rules.yaml` change, a PR and a deploy.

---

## v1.5 — Hybrid (one LLM call at a fixed node)

Same as v1, except step 7 has a second chance. **Control flow is still fixed in code**; the LLM is
just a function called at one node.

```
1) – 6)  identical to v1
      ↓
7) Rule Engine       match? → continue at 8), decided_by = rules
      ↓ no match
7b) LLM classify     one call: "pick category + urgency from this allow-list"
      ↓
7c) Schema gate      valid JSON, values in taxonomy? no → 12) Human Triage Queue
      ↓
8) – 12) identical to v1, decided_by = llm_node
```

**Why it exists:** it separates "does an LLM help?" from "does an *agent* help?".
If v1.5 matches v2 on the out-of-distribution split, the agent's extra complexity isn't earning its place.

---

## v2 — Agentic workflow

A deterministic shell around one reasoning loop. Only step 7 decides its own path.

```
1) Intake            ┐
2) Queue & Dedupe    │ same v1 code, imported, not rewritten
3) Parser            │
4) Extractor         ┘
      ↓
5) Input Guardrail   5a) PII swap: names, emails, employee IDs → tokens like <EMP_1>
                         (the token → real value map stays in the shell; the model never sees it)
                     5b) injection check: flag suspicious text; ticket always passed as data, never as instructions
      ↓
6) Budget Governor   start the clock: max tokens, max agent steps, max seconds
      ↓
7) Orchestrator Agent (ReAct loop, the only non-fixed control flow)
     7a) model reads the ticket and the tool list
     7b) model picks a tool, or decides it is done
           kb_search        search runbooks (local embeddings + FAISS)
           cmdb_lookup      same SQL function as v1 step 6
           similar_tickets  search resolved ticket history
           apply_rules      v1's rule engine, step 7, as a tool
     7c) shell runs the tool (swapping tokens back to real IDs), returns the result
     7d) scratchpad stores the step; too long → summarise older steps
     7e) repeat 7a–7d until the model returns a decision, or the budget runs out
      ↓
8) Schema Gate       valid TriageDecision? category and group in taxonomy?
                     no → back to 7 with the error message (limited repair attempts)
      ↓
9) Critic            9a) code: every citation id was actually returned by a tool in this run
                     9b) LLM:  every claim is supported by the cited text
                     fails → back to 7 to re-reason
      ↓
10) Confidence Gate  confidence computed from signals (agrees with apply_rules, critic passed,
                     retrieval strength, repair count) — not the model's own opinion
                     ≥ threshold AND cited AND not high blast radius (P1, security) → AUTO_RESOLVED
                     otherwise → HUMAN_REVIEW with draft decision + evidence attached
      ↓
11) Responder + ITSM Write   same v1 code; tokens in the draft reply swapped back to real values

Fallback   model down, budget spent, or repairs exhausted → run v1 steps 6–12 → decided_by = rules_fallback
Feedback   a human corrects a decision → saved as a new labelled case in data/golden/feedback.jsonl
```

---

## Who decides control flow — the organising idea

| Step | Uses an LLM? | Who decides what happens next | How it is tested |
|---|---|---|---|
| v1, all steps | No | Code | Unit tests, exact asserts |
| v1.5 step 7b | Yes | Code | Evals (output varies) |
| v2 steps 1–6, 8, 9a, 10, 11 | No | Code | Unit tests, exact asserts |
| v2 step 9b (critic) | Yes | Code | Evals |
| v2 step 7 (agent) | Yes | **The model** | Evals |

Two separate questions:

1. **Who decides control flow?** Code → workflow (automation). Model → agentic.
2. **Is a step's output deterministic?** Yes → unit test. No → eval.

Only v2 step 7 is agentic. Step 9b is non-deterministic but still a workflow step.
And inside step 7, `apply_rules` runs v1's rule engine: conventional automation running inside an agent.
