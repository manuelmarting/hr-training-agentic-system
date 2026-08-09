"""Repair-pass contract tests for `OpenAILLM`, mirroring
`test_agent_llm_gemini.py`'s Gemini coverage, plus `get_structured_llm` provider selection.

The OpenAI client itself is faked at the `langchain_openai.ChatOpenAI` seam that
`OpenAILLM.__init__` lazily imports, so no network/API key is involved.
"""

import langchain_openai
import pytest
from openai import OpenAIError
from pydantic import BaseModel

from app.agent.llm import (
    OpenAILLM,
    StructuredLLMError,
    get_structured_llm,
)


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


class _FakeChatOpenAI:
    def __init__(self, behaviors: list, **kwargs) -> None:
        self._structured = _FakeStructured(behaviors)

    def with_structured_output(self, output_model):
        return self._structured


def _patch_chat_openai(monkeypatch, behaviors: list) -> _FakeChatOpenAI:
    fake = _FakeChatOpenAI(behaviors)
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", lambda **kwargs: fake)
    return fake


async def _extract(monkeypatch, behaviors: list) -> _Out:
    _patch_chat_openai(monkeypatch, behaviors)
    llm = OpenAILLM(api_key="test-key")
    return await llm.extract(_Out, "system", "user")


@pytest.mark.asyncio
async def test_valid_output_returned_on_first_call(monkeypatch):
    result = await _extract(monkeypatch, [_Out(value="ok")])
    assert result.value == "ok"


@pytest.mark.asyncio
async def test_malformed_output_triggers_repair_and_succeeds(monkeypatch):
    result = await _extract(monkeypatch, [OpenAIError("bad json"), _Out(value="repaired")])
    assert result.value == "repaired"


@pytest.mark.asyncio
async def test_repair_failure_raises_structured_llm_error(monkeypatch):
    with pytest.raises(StructuredLLMError):
        await _extract(
            monkeypatch,
            [OpenAIError("bad json"), OpenAIError("still bad")],
        )


@pytest.mark.asyncio
async def test_transport_error_wrapped_as_structured_llm_error(monkeypatch):
    with pytest.raises(StructuredLLMError):
        await _extract(monkeypatch, [RuntimeError("connection reset")])


def test_missing_api_key_raises_before_any_call(monkeypatch):
    monkeypatch.setattr("app.config.settings.openai_api_key", None)
    with pytest.raises(StructuredLLMError):
        OpenAILLM(api_key=None)


def test_get_structured_llm_selects_openai(monkeypatch):
    monkeypatch.setattr("app.config.settings.openai_api_key", "test-key")
    assert isinstance(get_structured_llm(provider="openai"), OpenAILLM)
