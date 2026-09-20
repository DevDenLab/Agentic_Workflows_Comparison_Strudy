"""Input Guardrail — docs/flows.md v2 step 5.

Two independent jobs:
  - PiiGuardrail: swap emails and employee ids for tokens before the model ever sees the ticket.
    The token -> real value map lives only in the shell (this object); tools that need a real
    value (cmdb_lookup) detokenize an argument on the way in and retokenize a result on the way
    out, so a real value only ever exists inside the shell's own process, never in a prompt.
  - InjectionDetector: flags ticket text that looks like it is trying to give the model
    instructions. It is not itself a defence — the defence is architectural (every tool is
    read-only, and the ticket is always framed as data) — this only makes the attempt visible in
    the audit trail.
"""

import re
from dataclasses import dataclass, field

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_EMPLOYEE_ID = re.compile(r"\bE\d{6}\b")

_INJECTION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore (?:all |the )?(?:previous|prior|above) instructions",
        r"disregard (?:the |your )?(?:previous |prior )?(?:instructions|guidelines|rules)",
        r"system\s*:",
        r"you are now in \w+ mode",
        r"new (?:rule|policy|instructions?) from",
        r"do not (?:escalate|log|record) this",
        r"reply with (?:exactly|only)",
        r"print your (?:system prompt|instructions|tools)",
    )
)


@dataclass(frozen=True, slots=True)
class RedactedText:
    subject: str
    text: str


class PiiGuardrail:
    """One instance per ticket. Tokens are stable within that instance: the same email always
    gets the same token, so the model can still reason about "is this the same person" across
    a ticket without ever seeing who that person is."""

    def __init__(self) -> None:
        self._token_by_value: dict[str, str] = {}
        self._value_by_token: dict[str, str] = {}
        self._next_email = 1
        self._next_employee = 1

    def redact(self, subject: str, text: str) -> RedactedText:
        return RedactedText(self._redact_string(subject), self._redact_string(text))

    def _redact_string(self, value: str) -> str:
        value = _EMPLOYEE_ID.sub(lambda m: self._token_for(m.group(0), "employee"), value)
        return _EMAIL.sub(lambda m: self._token_for(m.group(0), "email"), value)

    def _token_for(self, real_value: str, kind: str) -> str:
        if real_value in self._token_by_value:
            return self._token_by_value[real_value]
        if kind == "employee":
            token = f"<EMP_{self._next_employee}>"
            self._next_employee += 1
        else:
            token = f"<EMAIL_{self._next_email}>"
            self._next_email += 1
        self._token_by_value[real_value] = token
        self._value_by_token[token] = real_value
        return token

    def detokenize(self, value: str | None) -> str | None:
        """Real value for a token (a tool argument from the model), or `value` unchanged if it
        isn't a token this guardrail issued — a hallucinated or literal argument just won't match
        anything real downstream, which is safe."""
        if value is None:
            return None
        return self._value_by_token.get(value, value)

    def retokenize(self, value: str | None) -> str | None:
        """The token for a real value (sanitising a tool result before it reaches the model),
        minting a fresh token if this value hasn't been seen in the ticket text itself."""
        if value is None:
            return None
        if value in self._token_by_value:
            return self._token_by_value[value]
        kind = "employee" if _EMPLOYEE_ID.fullmatch(value) else "email"
        return (
            self._token_for(value, kind) if kind == "employee" or _EMAIL.fullmatch(value) else value
        )


@dataclass(frozen=True, slots=True)
class InjectionScan:
    suspicious: bool
    matched_phrases: tuple[str, ...] = field(default_factory=tuple)


class InjectionDetector:
    def scan(self, text: str) -> InjectionScan:
        matches = tuple(pattern.pattern for pattern in _INJECTION_PATTERNS if pattern.search(text))
        return InjectionScan(suspicious=bool(matches), matched_phrases=matches)
