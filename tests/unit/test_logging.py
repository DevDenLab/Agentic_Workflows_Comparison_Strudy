import io
import json
from collections.abc import Iterator
from uuid import uuid4

import pytest
import structlog

from triage.observability.logging import configure_logging, correlation_scope, get_logger


@pytest.fixture(autouse=True)
def _reset_structlog() -> Iterator[None]:
    yield
    structlog.reset_defaults()


def _lines(buffer: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in buffer.getvalue().splitlines()]


def test_correlation_id_is_attached_inside_scope_and_gone_after() -> None:
    buffer = io.StringIO()
    configure_logging("INFO", "json", stream=buffer)
    log = get_logger("parser")
    correlation_id = uuid4()

    with correlation_scope(correlation_id):
        log.info("parsed")
    log.info("idle")

    inside, outside = _lines(buffer)
    assert inside["correlation_id"] == str(correlation_id)
    assert inside["component"] == "parser"
    assert inside["event"] == "parsed"
    assert "correlation_id" not in outside


def test_level_filter_drops_lower_levels() -> None:
    buffer = io.StringIO()
    configure_logging("WARNING", "json", stream=buffer)
    log = get_logger("queue")

    log.info("hidden")
    log.warning("shown")

    assert [line["event"] for line in _lines(buffer)] == ["shown"]
