"""Step 3 — Parser: turn a raw email or form body into clean ticket text.

Removes MIME structure, HTML, quoted reply history and signatures. Nothing is interpreted here.
"""

import re
from email import message_from_string, policy
from email.message import EmailMessage
from html.parser import HTMLParser

from pydantic import Field

from triage.config import ConfigModel, RegexPattern
from triage.contracts import Channel, InboundMessage


class ParserConfig(ConfigModel):
    quote_markers: tuple[RegexPattern, ...] = Field(min_length=1)
    signature_markers: tuple[RegexPattern, ...] = Field(min_length=1)


class Parser:
    def __init__(self, config: ParserConfig) -> None:
        self._markers = tuple(
            re.compile(pattern, re.IGNORECASE)
            for pattern in (*config.quote_markers, *config.signature_markers)
        )

    def parse(self, message: InboundMessage) -> str:
        if message.channel is Channel.EMAIL:
            return self.clean(email_body(message.raw_body))
        return self.clean(message.raw_body)

    def clean(self, body: str) -> str:
        kept: list[str] = []
        seen_content = False
        for raw_line in body.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = re.sub(r"[^\S\n]+", " ", raw_line).strip()
            if seen_content and any(marker.match(line) for marker in self._markers):
                break
            kept.append(line)
            seen_content = seen_content or bool(line)
        return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def email_body(raw: str) -> str:
    """The best text part of an RFC 822 message: text/plain if present, else text/html as text."""
    message = message_from_string(raw, policy=policy.default)
    if not isinstance(message, EmailMessage):
        raise TypeError("policy.default should always produce EmailMessage")
    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    content = part.get_content()
    text = content if isinstance(content, str) else ""
    return html_to_text(text) if part.get_content_type() == "text/html" else text


class _HtmlToText(HTMLParser):
    _BLOCK_TAGS = frozenset(
        {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "table"}
    )
    _SKIP_TAGS = frozenset({"script", "style", "head"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._chunks.append(data)

    def text(self) -> str:
        return "".join(self._chunks)


def html_to_text(html: str) -> str:
    converter = _HtmlToText()
    converter.feed(html)
    converter.close()
    return converter.text()
