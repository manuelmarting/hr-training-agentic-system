"""Structured-output LLM helper with a repair pass (CLAUDE.md: "repair-once, then fallback").

This is the single structured-extraction primitive both workflows share — the studio's
extraction passes and (later) workflow 1's `evaluate`/`memory` nodes call `StructuredLLM`.
The contract is deliberately small: given an output model + a system/user prompt, return a
validated instance or raise `StructuredLLMError`. Callers own the *fallback* (an empty
result, a safe default) so the failure policy lives with the caller's domain, not here.

The concrete Anthropic client is imported lazily inside `AnthropicLLM`, so the
pipeline and its contract tests import this module without pulling in `langchain-anthropic`
or needing an API key — tests inject a stub that satisfies the `StructuredLLM` protocol.
"""

from __future__ import annotations

import logging
from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class StructuredLLMError(RuntimeError):
    """The model could not produce output matching the schema, even after one repair."""


def _log_result(output_model: type[BaseModel], user: str, result: BaseModel) -> None:
    logger.info("%s | input=%r | output=%s", output_model.__name__, user, result.model_dump_json())


@runtime_checkable
class StructuredLLM(Protocol):
    """The orchestrator's LLM boundary: structured extraction plus tool-selection calls."""

    async def extract(self, output_model: type[T], system: str, user: str) -> T:
        """Return a validated `output_model` instance, or raise `StructuredLLMError`."""
        ...

    async def acall_with_tools(self, messages: list, tools: list) -> object:
        """Return the model's next message (an `AIMessage`, possibly carrying
        `.tool_calls`) given the running conversation and the available tool specs."""
        ...


class _ProviderLLM:
    """Shared `StructuredLLM` implementation: repair-once-then-raise (CLAUDE.md).

    Subclasses build `self._chat` in `__init__` and set `self._validation_errors` to
    the provider-specific exception type(s) that mean "invalid output" — checked
    alongside `pydantic.ValidationError`, which every provider can raise.
    """

    _chat: object
    _validation_errors: tuple[type[Exception], ...] = ()

    async def extract(self, output_model: type[T], system: str, user: str) -> T:
        from pydantic import ValidationError

        invalid_output = (ValidationError, *self._validation_errors)
        structured = self._chat.with_structured_output(output_model)
        try:
            result = await structured.ainvoke([("system", system), ("user", user)])
            _log_result(output_model, user, result)
            return result
        except invalid_output as first_error:
            logger.warning("structured extraction invalid, attempting repair: %s", first_error)
            repair_user = (
                f"{user}\n\n"
                "Your previous response did not match the required schema. "
                f"Error:\n{first_error}\n"
                "Return a corrected response that strictly matches the schema."
            )
            try:
                result = await structured.ainvoke([("system", system), ("user", repair_user)])
                _log_result(output_model, repair_user, result)
                return result
            except invalid_output as second_error:
                raise StructuredLLMError(str(second_error)) from second_error
        except Exception as transport_error:  # noqa: BLE001 - boundary: wrap into one domain error
            raise StructuredLLMError(str(transport_error)) from transport_error

    async def acall_with_tools(self, messages: list, tools: list) -> object:
        return await self._chat.bind_tools(tools).ainvoke(messages)


class AnthropicLLM(_ProviderLLM):
    """`StructuredLLM` backed by `langchain-anthropic`. Defaults to `settings.extraction_model`."""

    def __init__(
        self,
        model: str | None = None,
        *,
        api_key: str | None = None,
        max_tokens: int | None = None,
    ) -> None:
        # Lazy import: keeps this dependency out of the unit-test path.
        from langchain_anthropic import ChatAnthropic
        from langchain_core.exceptions import OutputParserException

        from app.config import settings

        key = api_key or settings.anthropic_api_key
        if not key:
            raise StructuredLLMError("no Anthropic API key configured (settings.anthropic_api_key)")
        self._chat = ChatAnthropic(
            model=model or settings.extraction_model,
            api_key=key,
            max_tokens=max_tokens or settings.extraction_max_tokens,
        )
        self._validation_errors = (OutputParserException,)


class GeminiLLM(_ProviderLLM):
    """`StructuredLLM` backed by `langchain-google-genai`.

    Defaults to `settings.gemini_extraction_model`.
    """

    def __init__(
        self,
        model: str | None = None,
        *,
        api_key: str | None = None,
        max_tokens: int | None = None,
    ) -> None:
        # Lazy import: keeps this dependency out of the unit-test path.
        from google.api_core.exceptions import GoogleAPIError
        from langchain_google_genai import ChatGoogleGenerativeAI

        from app.config import settings

        key = api_key or settings.gemini_api_key
        if not key:
            raise StructuredLLMError("no Gemini API key configured (settings.gemini_api_key)")
        self._chat = ChatGoogleGenerativeAI(
            model=model or settings.gemini_extraction_model,
            google_api_key=key,
            max_tokens=max_tokens or settings.extraction_max_tokens,
        )
        self._validation_errors = (GoogleAPIError,)


class OpenAILLM(_ProviderLLM):
    """`StructuredLLM` backed by `langchain-openai`.

    Defaults to `settings.openai_extraction_model`.
    """

    def __init__(
        self,
        model: str | None = None,
        *,
        api_key: str | None = None,
        max_tokens: int | None = None,
    ) -> None:
        # Lazy import: keeps this dependency out of the unit-test path.
        from langchain_openai import ChatOpenAI
        from openai import OpenAIError

        from app.config import settings

        key = api_key or settings.openai_api_key
        if not key:
            raise StructuredLLMError("no OpenAI API key configured (settings.openai_api_key)")
        self._chat = ChatOpenAI(
            model=model or settings.openai_extraction_model,
            api_key=key,
            max_tokens=max_tokens or settings.extraction_max_tokens,
        )
        self._validation_errors = (OpenAIError,)


def get_structured_llm(
    provider: str | None = None,
    *,
    model: str | None = None,
    max_tokens: int | None = None,
) -> StructuredLLM:
    """Build the configured `StructuredLLM` (defaults to `settings.llm_provider`)."""
    from app.config import settings

    resolved = provider or settings.llm_provider
    if resolved == "gemini":
        return GeminiLLM(model, max_tokens=max_tokens)
    if resolved == "anthropic":
        return AnthropicLLM(model, max_tokens=max_tokens)
    if resolved == "openai":
        return OpenAILLM(model, max_tokens=max_tokens)
    raise StructuredLLMError(f"unknown llm_provider: {resolved!r}")
