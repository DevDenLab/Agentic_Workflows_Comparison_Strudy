"""JSON logs where every line inside a ticket's processing carries that ticket's correlation id.

structlog configuration is process-global by nature, so `configure_logging` is called once, from the
composition root. Components ask for a logger bound to their diagram component id.
"""

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal, TextIO
from uuid import UUID

import structlog
from structlog.typing import FilteringBoundLogger, Processor


def configure_logging(
    level: str = "INFO",
    fmt: Literal["json", "console"] = "json",
    stream: TextIO | None = None,
) -> None:
    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if fmt == "json"
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[level.upper()]
        ),
        logger_factory=structlog.PrintLoggerFactory(file=stream or sys.stderr),
        cache_logger_on_first_use=False,
    )


def get_logger(component: str) -> FilteringBoundLogger:
    logger: FilteringBoundLogger = structlog.get_logger()
    return logger.bind(component=component)


@contextmanager
def correlation_scope(correlation_id: UUID) -> Iterator[None]:
    """Attach `correlation_id` to every log line emitted inside the block, from any component."""
    with structlog.contextvars.bound_contextvars(correlation_id=str(correlation_id)):
        yield
