from typing import Protocol, runtime_checkable

from triage.contracts.decision import TriageResult
from triage.contracts.ticket import InboundMessage


@runtime_checkable
class TriagePipeline(Protocol):
    """The one seam every implementation sits behind: v1 rules, v1.5 hybrid, v2 agent.

    `triage` does not raise for a bad ticket.
    Bad input is an outcome (`human_review`), not an exception.
    """

    @property
    def name(self) -> str: ...

    def triage(self, message: InboundMessage) -> TriageResult: ...
