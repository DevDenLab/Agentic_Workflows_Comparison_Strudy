"""Budget Governor — docs/flows.md v2 step 6.

A hard ceiling on one ticket's agent loop: steps, tokens, wall-clock. Exceeding any of them raises
`BudgetExceeded`, which the pipeline treats exactly like a model outage: fall back to v1.
"""

from pydantic import Field

from triage.clock import Clock
from triage.config import ConfigModel


class BudgetConfig(ConfigModel):
    """config/agent.yaml: budget section."""

    max_steps: int = Field(gt=0)
    max_total_tokens: int = Field(gt=0)
    max_wall_seconds: float = Field(gt=0)


class BudgetExceeded(Exception):  # noqa: N818 - reads better without an Error suffix
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class BudgetGovernor:
    def __init__(self, config: BudgetConfig, clock: Clock) -> None:
        self._config = config
        self._clock = clock
        self._started = clock.monotonic()
        self.steps = 0
        self.total_tokens = 0

    def check(self) -> None:
        """Call before each LLM call. Raises if the budget is already spent."""
        if self.steps >= self._config.max_steps:
            raise BudgetExceeded(f"max_steps ({self._config.max_steps}) reached")
        if self.total_tokens >= self._config.max_total_tokens:
            raise BudgetExceeded(f"max_total_tokens ({self._config.max_total_tokens}) reached")
        elapsed = self._clock.monotonic() - self._started
        if elapsed >= self._config.max_wall_seconds:
            raise BudgetExceeded(f"max_wall_seconds ({self._config.max_wall_seconds}) reached")

    def record(self, *, prompt_tokens: int, completion_tokens: int) -> None:
        self.steps += 1
        self.total_tokens += prompt_tokens + completion_tokens

    @property
    def elapsed_seconds(self) -> float:
        return self._clock.monotonic() - self._started
