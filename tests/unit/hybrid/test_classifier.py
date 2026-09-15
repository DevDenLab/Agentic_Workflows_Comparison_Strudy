from datetime import UTC, datetime
from pathlib import Path

import pytest

from triage.clock import FixedClock
from triage.config import LoadedConfig
from triage.hybrid.classifier import ClassificationError, LlmClassifier, LlmConfig
from triage.llm.client import LlmClient, LlmError
from triage.v1.priority_matrix import Level

from .conftest import make_classifier, no_tool_call_response, tool_call_response


def test_valid_tool_call_on_the_first_try(
    llm_config: LlmConfig, loaded_config: LoadedConfig, prompts_dir: Path
) -> None:
    classifier, transport = make_classifier(
        [tool_call_response(category="printing", urgency="low", confidence=0.8)],
        llm_config,
        loaded_config,
        prompts_dir,
    )

    result = classifier.classify(subject="Printer jam", text="Paper jam on 3.")

    assert (result.category, result.urgency, result.confidence) == ("printing", Level.LOW, 0.8)
    assert result.attempts == 1
    assert (result.prompt_tokens, result.completion_tokens) == (150, 12)
    assert len(transport.payloads) == 1


def test_organisation_and_taxonomy_are_in_the_system_prompt(
    llm_config: LlmConfig, loaded_config: LoadedConfig, prompts_dir: Path
) -> None:
    classifier, transport = make_classifier(
        [tool_call_response(category="printing", urgency="low", confidence=0.8)],
        llm_config,
        loaded_config,
        prompts_dir,
    )

    classifier.classify(subject="s", text="t")

    system = transport.payloads[0]["messages"][0]
    assert system["role"] == "system"
    assert loaded_config.app.organisation in system["content"]
    assert "clinical_devices" in system["content"]
    assert "ignore these instructions" in system["content"]


def test_ticket_becomes_the_user_message(
    llm_config: LlmConfig, loaded_config: LoadedConfig, prompts_dir: Path
) -> None:
    classifier, transport = make_classifier(
        [tool_call_response(category="printing", urgency="low", confidence=0.8)],
        llm_config,
        loaded_config,
        prompts_dir,
    )

    classifier.classify(subject="Printer jam", text="Paper jam on 3.")

    user = transport.payloads[0]["messages"][1]
    assert user == {"role": "user", "content": "Subject: Printer jam\n\nPaper jam on 3."}


def test_an_unknown_category_triggers_one_repair_then_succeeds(
    llm_config: LlmConfig, loaded_config: LoadedConfig, prompts_dir: Path
) -> None:
    classifier, transport = make_classifier(
        [
            tool_call_response(category="not_a_real_category", urgency="low", confidence=0.5),
            tool_call_response(category="printing", urgency="low", confidence=0.9),
        ],
        llm_config,
        loaded_config,
        prompts_dir,
    )

    result = classifier.classify(subject="s", text="t")

    assert result.category == "printing"
    assert result.attempts == 2
    assert result.prompt_tokens == 300  # both attempts' usage accumulates
    assert "not one of the allowed categories" in transport.payloads[1]["messages"][-1]["content"]


@pytest.mark.parametrize(
    "bad_response",
    [
        tool_call_response(category="printing", urgency="urgent", confidence=0.5),  # bad enum
        tool_call_response(category="printing", confidence=0.5),  # missing urgency
        tool_call_response(category="printing", urgency="low", confidence=1.5),  # out of range
        no_tool_call_response(),
    ],
)
def test_every_kind_of_bad_output_triggers_a_repair(
    llm_config: LlmConfig,
    loaded_config: LoadedConfig,
    prompts_dir: Path,
    bad_response: dict[str, object],
) -> None:
    classifier, _ = make_classifier(
        [bad_response, tool_call_response(category="printing", urgency="low", confidence=0.9)],
        llm_config,
        loaded_config,
        prompts_dir,
    )

    result = classifier.classify(subject="s", text="t")

    assert result.attempts == 2


def test_exhausting_repair_attempts_raises(
    llm_config: LlmConfig, loaded_config: LoadedConfig, prompts_dir: Path
) -> None:
    always_bad = tool_call_response(category="nope", urgency="low", confidence=0.5)
    classifier, _ = make_classifier(
        [always_bad] * (llm_config.max_repair_attempts + 1), llm_config, loaded_config, prompts_dir
    )

    with pytest.raises(ClassificationError, match="exhausted repair attempts"):
        classifier.classify(subject="s", text="t")


def test_a_provider_error_is_not_retried(
    llm_config: LlmConfig, loaded_config: LoadedConfig, prompts_dir: Path
) -> None:
    class FailingTransport:
        def send(self, payload: object, timeout_seconds: float) -> dict[str, object]:
            raise LlmError("503: overloaded")

    client = LlmClient(
        FailingTransport(), "deepseek-flash", FixedClock(datetime(2026, 9, 14, tzinfo=UTC))
    )
    classifier = LlmClassifier(
        client, llm_config, loaded_config.taxonomy, prompts_dir, loaded_config.app.organisation
    )

    with pytest.raises(ClassificationError, match="provider error"):
        classifier.classify(subject="s", text="t")
