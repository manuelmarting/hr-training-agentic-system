"""Repair-pass contract tests for `AnthropicLLM` (plan §4 Phase 2 exit
criteria): valid output, malformed → repair succeeds, repair fails → fallback.

The Anthropic client itself is faked at the `langchain_anthropic.ChatAnthropic`
seam that `AnthropicLLM.__init__` lazily imports, so no network/API key
is involved.
"""

import langchain_anthropic
import pytest
from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel

from app.agent.llm import AnthropicLLM, StructuredLLMError


class _Out(BaseModel):
    value: str


class _FakeStructured:
    """Stands in for `chat.with_structured_output(model)`."""

    def __init__(self, behaviors: list) -> None:
        self._behaviors = list(behaviors)
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        behavior = self._behaviors.pop(0)
        if isinstance(behavior, Exception):
            raise behavior
        return behavior


class _FakeChatAnthropic:
    def __init__(self, behaviors: list, **kwargs) -> None:
        self._structured = _FakeStructured(behaviors)

    def with_structured_output(self, output_model):
        return self._structured


def _patch_chat_anthropic(monkeypatch, behaviors: list) -> _FakeChatAnthropic:
    fake = _FakeChatAnthropic(behaviors)
    monkeypatch.setattr(langchain_anthropic, "ChatAnthropic", lambda **kwargs: fake)
    return fake


async def _extract(monkeypatch, behaviors: list) -> _Out:
    _patch_chat_anthropic(monkeypatch, behaviors)
    llm = AnthropicLLM(api_key="test-key")
    return await llm.extract(_Out, "system", "user")


@pytest.mark.asyncio
async def test_valid_output_returned_on_first_call(monkeypatch):
    result = await _extract(monkeypatch, [_Out(value="ok")])
    assert result.value == "ok"


@pytest.mark.asyncio
async def test_malformed_output_triggers_repair_and_succeeds(monkeypatch):
    result = await _extract(
        monkeypatch, [OutputParserException("bad json"), _Out(value="repaired")]
    )
    assert result.value == "repaired"


@pytest.mark.asyncio
async def test_repair_failure_raises_structured_llm_error(monkeypatch):
    with pytest.raises(StructuredLLMError):
        await _extract(
            monkeypatch,
            [OutputParserException("bad json"), OutputParserException("still bad")],
        )


@pytest.mark.asyncio
async def test_transport_error_wrapped_as_structured_llm_error(monkeypatch):
    with pytest.raises(StructuredLLMError):
        await _extract(monkeypatch, [RuntimeError("connection reset")])


def test_missing_api_key_raises_before_any_call(monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_api_key", None)
    with pytest.raises(StructuredLLMError):
        AnthropicLLM(api_key=None)
