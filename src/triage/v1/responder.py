"""Step 11 — Template Responder: the first reply to the requester, one Jinja2 template per category.

Templates live in config/templates/. Undefined variables raise instead of rendering blank, and every
taxonomy category must have a template, checked at start-up.
"""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from triage.config import ConfigError
from triage.contracts import Priority, Taxonomy, Ticket
from triage.v1.cmdb import CmdbContext


class Responder:
    def __init__(self, templates_dir: Path, taxonomy: Taxonomy, timezone: str) -> None:
        missing = sorted(
            c for c in taxonomy.category_ids if not (templates_dir / f"{c}.j2").is_file()
        )
        if missing:
            raise ConfigError(f"{templates_dir}: no response template for categories {missing}")
        self._tz = ZoneInfo(timezone)
        self._env = Environment(
            loader=FileSystemLoader(templates_dir),
            undefined=StrictUndefined,
            autoescape=False,  # noqa: S701 - renders plain-text email, not HTML
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=False,
        )
        self._env.filters["humanise"] = _humanise

    def render(
        self,
        *,
        ticket: Ticket,
        category: str,
        priority: Priority,
        assignment_group: str,
        due_at: datetime,
        context: CmdbContext,
    ) -> str:
        first_name = context.employee.full_name.split()[0] if context.employee else "there"
        return (
            self._env.get_template(f"{category}.j2")
            .render(
                first_name=first_name,
                subject=ticket.subject or "your request",
                priority=priority.value,
                assignment_group=assignment_group,
                due_local=due_at.astimezone(self._tz).strftime("%a %d %b %Y, %H:%M %Z"),
            )
            .strip()
        )


def _humanise(identifier: str) -> str:
    return identifier.replace("_", " ").title()
