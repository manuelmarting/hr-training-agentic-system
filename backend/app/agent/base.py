from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.schemas.chat import ChatMessage


class Agent(ABC):
    """Interface every agent implementation must satisfy.

    No concrete framework (Anthropic SDK, LangChain, etc.) is wired in yet —
    swap `EchoAgent` for a real implementation once that decision is made.
    """

    @abstractmethod
    async def stream_reply(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        """Yield the reply incrementally, token/chunk by chunk."""
        raise NotImplementedError
        yield  # pragma: no cover - makes this an async generator for type checkers


class EchoAgent(Agent):
    """Trivial stub agent: echoes the last user message back, word by word."""

    async def stream_reply(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        last_message = messages[-1].content if messages else ""
        for word in last_message.split():
            yield word + " "


def get_agent() -> Agent:
    return EchoAgent()
