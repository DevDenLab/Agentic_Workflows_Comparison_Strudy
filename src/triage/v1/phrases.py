"""Case-insensitive whole-word phrase matching, shared by the rule engine and priority matrix."""

import re
from typing import Annotated

from pydantic import StringConstraints

Phrase = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=1)]


def compile_phrase(phrase: str) -> re.Pattern[str]:
    """`wifi` matches "WiFi down", not "wifidget". Spaces in a phrase match any whitespace."""
    words = (re.escape(word) for word in phrase.split())
    return re.compile(r"(?<!\w)" + r"\s+".join(words) + r"(?!\w)", re.IGNORECASE)
