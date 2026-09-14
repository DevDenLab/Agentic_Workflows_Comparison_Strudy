# Architecture diagrams

`v1_conventional_architecture.json` and `v2_agentic_architecture.json` are art-direction specs for an
image model; `IMAGE_PROMPT.md` is the prompt to use with them. Component `id`s in the specs match module
names under `src/triage/`.

## Known problems, to fix before regenerating (Stage 5)

| Diagram | Problem | Fix |
|---|---|---|
| v1 PNG | "invalid input" arrow points at CMDB Lookup | Spec is right (parser → human_queue); regenerate |
| v1 spec | "no match — 45% of volume" is not a measured number | Replace with the benchmark's measured rule-miss rate |
| v1 spec | CMDB feeds only the routing table | CMDB also feeds the priority matrix (impact comes from service criticality) |
| v2 spec | `similar_tickets` tool missing | Add a fourth tool card |
| v2 spec | Dashed "reasoning" box contains the deterministic tools and excludes the LLM critic | Box the agent's control flow only; mark the critic as an LLM step inside the fixed workflow |
| v2 spec | Feedback arrow goes to `kb_search` | Point it at the eval set (`data/golden/feedback.jsonl`) |
| v2 PNG | Rendering glitches: "grp_shell" leaked into a label, "instal" typo, missing group label | Regenerate |
| v2 PNG | Not yet saved to disk | Add `v2_agentic_architecture.png` here |
