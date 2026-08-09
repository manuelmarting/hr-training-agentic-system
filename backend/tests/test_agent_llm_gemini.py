"""Repair-pass contract tests for `GeminiLLM`, mirroring
`test_agent_llm.py`'s Anthropic coverage, plus `get_structured_llm` provider selection.

The Gemini client itself is faked at the `langchain_google_genai.ChatGoogleGenerativeAI`
seam that `GeminiLLM.__init__` lazily imports, so no network/API key is involved.
"""

import langchain_google_genai
import pytest
from google.api_core.exceptions import GoogleAPIError
from pydantic import BaseModel

from app.agent.llm import (
    AnthropicLLM,
    GeminiLLM,
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


class _FakeChatGoogleGenerativeAI:
    def __init__(self, behaviors: list, **kwargs) -> None:
        self._structured = _FakeStructured(behaviors)

    def with_structured_output(self, output_model):
        return self._structured


def _patch_chat_gemini(monkeypatch, behaviors: list) -> _FakeChatGoogleGenerativeAI:
    fake = _FakeChatGoogleGenerativeAI(behaviors)
    monkeypatch.setattr(langchain_google_genai, "ChatGoogleGenerativeAI", lambda **kwargs: fake)
    return fake


async def _extract(monkeypatch, behaviors: list) -> _Out:
    _patch_chat_gemini(monkeypatch, behaviors)
    llm = GeminiLLM(api_key="test-key")
    return await llm.extract(_Out, "system", "user")


@pytest.mark.asyncio
async def test_valid_output_returned_on_first_call(monkeypatch):
    result = await _extract(monkeypatch, [_Out(value="ok")])
    assert result.value == "ok"


@pytest.mark.asyncio
async def test_malformed_output_triggers_repair_and_succeeds(monkeypatch):
    result = await _extract(monkeypatch, [GoogleAPIError("bad json"), _Out(value="repaired")])
    assert result.value == "repaired"


@pytest.mark.asyncio
async def test_repair_failure_raises_structured_llm_error(monkeypatch):
    with pytest.raises(StructuredLLMError):
        await _extract(
            monkeypatch,
            [GoogleAPIError("bad json"), GoogleAPIError("still bad")],
        )


@pytest.mark.asyncio
async def test_transport_error_wrapped_as_structured_llm_error(monkeypatch):
    with pytest.raises(StructuredLLMError):
        await _extract(monkeypatch, [RuntimeError("connection reset")])


def test_missing_api_key_raises_before_any_call(monkeypatch):
    monkeypatch.setattr("app.config.settings.gemini_api_key", None)
    with pytest.raises(StructuredLLMError):
        GeminiLLM(api_key=None)


def test_get_structured_llm_defaults_to_gemini(monkeypatch):
    monkeypatch.setattr("app.config.settings.llm_provider", "gemini")
    monkeypatch.setattr("app.config.settings.gemini_api_key", "test-key")
    assert isinstance(get_structured_llm(), GeminiLLM)


def test_get_structured_llm_selects_anthropic(monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "test-key")
    assert isinstance(get_structured_llm(provider="anthropic"), AnthropicLLM)


def test_get_structured_llm_rejects_unknown_provider():
    with pytest.raises(StructuredLLMError):
        get_structured_llm(provider="not-a-provider")
