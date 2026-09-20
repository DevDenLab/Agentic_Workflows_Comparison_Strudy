"""Critic — docs/flows.md v2 steps 9a/9b. Two independent checks; both must pass to be "grounded".

9a) code: every citation the agent gave actually names a source_id some tool returned this run.
    Deterministic, no LLM call, tested with exact asserts like any other code in this project.
9b) LLM: a second, separate model pass asks "is every claim in this decision actually supported by
    its cited excerpts?" It never sees the agent's own reasoning or tool trace — only the decision
    and the cited text — so it cannot simply agree with itself.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import Field

from triage.config import ConfigModel
from triage.llm.client import LlmClient, LlmError, LlmMessage, tool_schema

CRITIC_TOOL = "critic_verdict"

_SYSTEM_PROMPT = """You are a grounding critic for an IT service-desk triage decision. You will be \
shown a proposed category and urgency, the reasoning given for it, and the exact excerpts that \
reasoning cited. Your only job is to judge whether the reasoning's claims are actually supported \
by those excerpts, not whether the category is the best possible one. Call critic_verdict once."""


class CriticConfig(ConfigModel):
    """config/agent.yaml: critic section."""

    temperature: float = Field(ge=0, le=2)
    max_output_tokens: int = Field(gt=0)
    timeout_seconds: float = Field(gt=0)
    extra_body: dict[str, object] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CriticVerdict:
    grounded: bool
    reason: str


class CriticError(Exception):
    """The critic pass itself failed (provider error or unusable output)."""


def citations_are_grounded(
    citations: Sequence[str], seen_source_ids: frozenset[str]
) -> tuple[bool, tuple[str, ...]]:
    """9a. Returns (grounded, unknown_citations) — unknown ones name what to tell the agent."""
    unknown = tuple(c for c in citations if c not in seen_source_ids)
    return (not unknown, unknown)


def _tool() -> dict[str, object]:
    return tool_schema(
        CRITIC_TOOL,
        "Give your grounding verdict.",
        {
            "type": "object",
            "properties": {
                "grounded": {"type": "boolean"},
                "reason": {"type": "string", "description": "One sentence."},
            },
            "required": ["grounded", "reason"],
            "additionalProperties": False,
        },
    )


class GroundingCritic:
    """9b. Uses `client` as given — the composition root decides whether that's CRITIC_MODEL or
    the same model as the orchestrator."""

    def __init__(self, client: LlmClient, config: CriticConfig) -> None:
        self._client = client
        self._config = config

    def review(
        self, *, category: str, urgency: str, rationale: str, cited_excerpts: Sequence[str]
    ) -> CriticVerdict:
        excerpts = "\n\n".join(f"- {excerpt}" for excerpt in cited_excerpts) or "(no citations)"
        user = (
            f"Proposed category: {category}\nProposed urgency: {urgency}\n"
            f"Reasoning given: {rationale}\n\nCited excerpts:\n{excerpts}"
        )
        try:
            result = self._client.complete(
                messages=[
                    LlmMessage(role="system", content=_SYSTEM_PROMPT),
                    LlmMessage(role="user", content=user),
                ],
                tools=[_tool()],
                tool_choice=CRITIC_TOOL,
                temperature=self._config.temperature,
                max_tokens=self._config.max_output_tokens,
                timeout_seconds=self._config.timeout_seconds,
                extra=self._config.extra_body,
            )
        except LlmError as exc:
            raise CriticError(f"provider error: {exc}") from exc

        call = next((c for c in result.tool_calls if c.name == CRITIC_TOOL), None)
        if call is None:
            raise CriticError("critic did not call critic_verdict")
        try:
            return CriticVerdict(bool(call.arguments["grounded"]), str(call.arguments["reason"]))
        except (KeyError, TypeError) as exc:
            raise CriticError(f"malformed critic_verdict arguments: {exc}") from exc
