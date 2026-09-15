"""LLM classification at the rule-miss node — docs/flows.md v1.5 step 7b.

Control flow is still fixed in code: the model is a function called at one point, not an agent.
Invalid output goes back to the model once per `max_repair_attempts`; still-invalid output is a
`ClassificationError`, which the pipeline treats exactly like a rule miss: human review.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import Field

from triage.config import ConfigModel
from triage.contracts import Taxonomy
from triage.llm.client import LlmClient, LlmError, LlmMessage, tool_schema
from triage.v1.priority_matrix import Level

CLASSIFY_TOOL = "classify_ticket"


class LlmConfig(ConfigModel):
    """config/llm.yaml"""

    version: str
    temperature: float = Field(ge=0, le=2)
    max_output_tokens: int = Field(gt=0)
    timeout_seconds: float = Field(gt=0)
    max_repair_attempts: int = Field(ge=0)
    seed: int | None = None
    extra_body: dict[str, object] = Field(default_factory=dict)
    """Provider-specific fields merged straight into the request (e.g. DeepSeek's `thinking`
    toggle: forced tool_choice needs thinking mode off). Ignored by providers that don't know
    the key, so this stays empty for OpenRouter/Ollama without touching the generic client."""


@dataclass(frozen=True, slots=True)
class Classification:
    category: str
    urgency: Level
    confidence: float
    prompt_tokens: int
    completion_tokens: int
    attempts: int


class ClassificationError(Exception):
    """The model never produced a usable classification within the repair budget."""


def _build_tool(taxonomy: Taxonomy) -> dict[str, object]:
    return tool_schema(
        CLASSIFY_TOOL,
        "Classify an IT service-desk ticket that no keyword rule matched.",
        {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": sorted(taxonomy.category_ids)},
                "urgency": {"type": "string", "enum": ["low", "medium", "high"]},
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "description": "How confident you are in this classification.",
                },
            },
            "required": ["category", "urgency", "confidence"],
            "additionalProperties": False,
        },
    )


def render_system_prompt(prompts_dir: Path, organisation: str, taxonomy: Taxonomy) -> str:
    env = Environment(
        loader=FileSystemLoader(prompts_dir),
        undefined=StrictUndefined,
        autoescape=False,  # noqa: S701 - a prompt string, not HTML
    )
    return env.get_template("classify_system.j2").render(
        organisation=organisation, categories=taxonomy.categories
    )


class LlmClassifier:
    def __init__(
        self,
        client: LlmClient,
        config: LlmConfig,
        taxonomy: Taxonomy,
        prompts_dir: Path,
        organisation: str,
    ) -> None:
        self._client = client
        self._config = config
        self._taxonomy = taxonomy
        self._tool = _build_tool(taxonomy)
        self._system_prompt = render_system_prompt(prompts_dir, organisation, taxonomy)

    def classify(self, *, subject: str, text: str) -> Classification:
        messages = [
            LlmMessage(role="system", content=self._system_prompt),
            LlmMessage(role="user", content=f"Subject: {subject}\n\n{text}"),
        ]
        prompt_tokens = completion_tokens = 0
        last_error = "no attempt made"

        for attempt in range(1, self._config.max_repair_attempts + 2):
            try:
                result = self._client.complete(
                    messages=messages,
                    tools=[self._tool],
                    tool_choice=CLASSIFY_TOOL,
                    temperature=self._config.temperature,
                    max_tokens=self._config.max_output_tokens,
                    timeout_seconds=self._config.timeout_seconds,
                    seed=self._config.seed,
                    extra=self._config.extra_body,
                )
            except LlmError as exc:
                raise ClassificationError(f"provider error: {exc}") from exc

            prompt_tokens += result.prompt_tokens
            completion_tokens += result.completion_tokens

            call = next((c for c in result.tool_calls if c.name == CLASSIFY_TOOL), None)
            if call is None:
                last_error = "model did not call classify_ticket"
            else:
                try:
                    classification = self._validate(
                        call.arguments, attempt, prompt_tokens, completion_tokens
                    )
                except ValueError as exc:
                    last_error = str(exc)
                else:
                    return classification

            messages = [
                *messages,
                LlmMessage(
                    role="user",
                    content=f"That was invalid: {last_error}. "
                    "Call classify_ticket again, correctly.",
                ),
            ]

        raise ClassificationError(f"exhausted repair attempts: {last_error}")

    def _validate(
        self, arguments: dict[str, object], attempt: int, prompt_tokens: int, completion_tokens: int
    ) -> Classification:
        try:
            category = str(arguments["category"])
            urgency = Level(str(arguments["urgency"]))
            confidence = float(arguments["confidence"])  # type: ignore[arg-type]
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError(f"malformed arguments {json.dumps(arguments)}: {exc}") from exc
        if category not in self._taxonomy.category_ids:
            raise ValueError(f"category {category!r} is not one of the allowed categories")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return Classification(
            category, urgency, confidence, prompt_tokens, completion_tokens, attempt
        )
