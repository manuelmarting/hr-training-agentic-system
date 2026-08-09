"""Channel-adaptive rendering: one core, two adapters (PRD §6.1, §7).

The graph produces a channel-agnostic `RenderIntent`; `render()` applies a declarative
`ChannelPolicy` to turn it into what actually gets sent. No LLM involvement — this is
the same "deterministic where the PRD says deterministic" posture as the mastery
engine and KG gating.
"""

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

ChannelName = Literal["telegram", "voice"]

_MARKDOWN_PATTERNS = [
    (re.compile(r"\[([^\]]+)\]\([^)]+\)"), r"\1"),  # [text](url) -> text
    (re.compile(r"(\*\*|__)(.*?)\1"), r"\2"),  # bold
    (re.compile(r"(\*|_)(.*?)\1"), r"\2"),  # italic
    (re.compile(r"`([^`]+)`"), r"\1"),  # inline code
]

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


class RenderIntent(BaseModel):
    """Channel-agnostic content the graph wants delivered this turn."""

    text: str
    options: list[str] = Field(default_factory=list)
    requires_confirmation: bool = False


class RenderedMessage(BaseModel):
    """What actually gets sent, after policy is applied."""

    text: str
    buttons: list[str] | None = None
    truncated: bool = False


@dataclass(frozen=True)
class ChannelPolicy:
    name: ChannelName
    max_chars: int | None
    max_sentences: int | None
    strip_markdown: bool
    use_inline_buttons: bool
    digit_confirmation: bool


TELEGRAM = ChannelPolicy(
    name="telegram",
    max_chars=4096,
    max_sentences=None,
    strip_markdown=False,
    use_inline_buttons=True,
    digit_confirmation=False,
)

VOICE = ChannelPolicy(
    name="voice",
    max_chars=None,
    max_sentences=2,
    strip_markdown=True,
    use_inline_buttons=False,
    digit_confirmation=True,
)

POLICIES: dict[ChannelName, ChannelPolicy] = {"telegram": TELEGRAM, "voice": VOICE}


def render(intent: RenderIntent, policy: ChannelPolicy) -> RenderedMessage:
    text = intent.text

    if policy.strip_markdown:
        text = _strip_markdown(text)

    if policy.max_sentences is not None:
        text = _truncate_sentences(text, policy.max_sentences)

    truncated = False
    if policy.max_chars is not None and len(text) > policy.max_chars:
        text = text[: policy.max_chars]
        truncated = True

    buttons = list(intent.options) if (policy.use_inline_buttons and intent.options) else None

    if policy.digit_confirmation and intent.requires_confirmation and intent.options:
        repeat_back = ", ".join(f"{i} for {opt}" for i, opt in enumerate(intent.options, start=1))
        text = f"{text} Say {repeat_back}."

    return RenderedMessage(text=text, buttons=buttons, truncated=truncated)


def _strip_markdown(text: str) -> str:
    for pattern, replacement in _MARKDOWN_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _truncate_sentences(text: str, max_sentences: int) -> str:
    sentences = _SENTENCE_SPLIT.split(text.strip())
    return " ".join(sentences[:max_sentences])
