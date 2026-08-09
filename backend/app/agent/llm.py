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
    """A structured-extraction boundary. Implementations validate against `output_model`."""

    async def extract(self, output_model: type[T], system: str, user: str) -> T:
        """Return a validated `output_model` instance, or raise `StructuredLLMError`."""
        ...


@runtime_checkable
class ToolCallingLLM(Protocol):
    """The orchestrator's tool-selection boundary — separate from `StructuredLLM`
    (which callers like `evaluate_turn`/`extract_and_gate_fact` depend on structurally
    via `isinstance` checks in tests) so adding this method never breaks those.
    """

    async def acall_with_tools(self, messages: list, tools: list) -> object:
        """Return the model's next message (an `AIMessage`, possibly carrying
        `.tool_calls`) given the running conversation and the available tool specs."""
        ...


class AnthropicLLM:
    """`StructuredLLM` backed by `langchain-anthropic` `.with_structured_output` (CLAUDE.md).

    On the first invalid response (schema/parse failure) it re-prompts once, appending the
    validation error, then raises `StructuredLLMError`. Transport errors are wrapped the same
    way so callers only ever handle one exception type.
    """

    def __init__(
        self,
        model: str | None = None,
        *,
        api_key: str | None = None,
        max_tokens: int | None = None,
    ) -> None:
        # Lazy import: keeps this dependency out of the unit-test path.
        from langchain_anthropic import ChatAnthropic

        from app.config import settings

        key = api_key or settings.anthropic_api_key
        if not key:
            raise StructuredLLMError("no Anthropic API key configured (settings.anthropic_api_key)")
        self._chat = ChatAnthropic(
            model=model or settings.extraction_model,
            api_key=key,
            max_tokens=max_tokens or settings.extraction_max_tokens,
        )

    async def extract(self, output_model: type[T], system: str, user: str) -> T:
        from langchain_core.exceptions import OutputParserException
        from pydantic import ValidationError

        structured = self._chat.with_structured_output(output_model)
        try:
            result = await structured.ainvoke([("system", system), ("user", user)])
            _log_result(output_model, user, result)
            return result
        except (OutputParserException, ValidationError) as first_error:
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
            except (OutputParserException, ValidationError) as second_error:
                raise StructuredLLMError(str(second_error)) from second_error
        except Exception as transport_error:  # noqa: BLE001 - boundary: wrap into one domain error
            raise StructuredLLMError(str(transport_error)) from transport_error

    async def acall_with_tools(self, messages: list, tools: list) -> object:
        return await self._chat.bind_tools(tools).ainvoke(messages)


class GeminiLLM:
    """`StructuredLLM` backed by `langchain-google-genai` `.with_structured_output`.

    Same repair-once-then-raise contract as `AnthropicLLM`; see that class for
    the rationale. Defaults to `settings.gemini_extraction_model`.
    """

    def __init__(
        self,
        model: str | None = None,
        *,
        api_key: str | None = None,
        max_tokens: int | None = None,
    ) -> None:
        # Lazy import: keeps this dependency out of the unit-test path.
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

    async def extract(self, output_model: type[T], system: str, user: str) -> T:
        from google.api_core.exceptions import GoogleAPIError
        from pydantic import ValidationError

        structured = self._chat.with_structured_output(output_model)
        try:
            result = await structured.ainvoke([("system", system), ("user", user)])
            _log_result(output_model, user, result)
            return result
        except (ValidationError, GoogleAPIError) as first_error:
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
            except (ValidationError, GoogleAPIError) as second_error:
                raise StructuredLLMError(str(second_error)) from second_error
        except Exception as transport_error:  # noqa: BLE001 - boundary: wrap into one domain error
            raise StructuredLLMError(str(transport_error)) from transport_error

    async def acall_with_tools(self, messages: list, tools: list) -> object:
        return await self._chat.bind_tools(tools).ainvoke(messages)


class OpenAILLM:
    """`StructuredLLM` backed by `langchain-openai` `.with_structured_output`.

    Same repair-once-then-raise contract as `AnthropicLLM`; see that class for
    the rationale. Defaults to `settings.openai_extraction_model`.
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

        from app.config import settings

        key = api_key or settings.openai_api_key
        if not key:
            raise StructuredLLMError("no OpenAI API key configured (settings.openai_api_key)")
        self._chat = ChatOpenAI(
            model=model or settings.openai_extraction_model,
            api_key=key,
            max_tokens=max_tokens or settings.extraction_max_tokens,
        )

    async def extract(self, output_model: type[T], system: str, user: str) -> T:
        from openai import OpenAIError
        from pydantic import ValidationError

        structured = self._chat.with_structured_output(output_model)
        try:
            result = await structured.ainvoke([("system", system), ("user", user)])
            _log_result(output_model, user, result)
            return result
        except (ValidationError, OpenAIError) as first_error:
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
            except (ValidationError, OpenAIError) as second_error:
                raise StructuredLLMError(str(second_error)) from second_error
        except Exception as transport_error:  # noqa: BLE001 - boundary: wrap into one domain error
            raise StructuredLLMError(str(transport_error)) from transport_error

    async def acall_with_tools(self, messages: list, tools: list) -> object:
        return await self._chat.bind_tools(tools).ainvoke(messages)


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
