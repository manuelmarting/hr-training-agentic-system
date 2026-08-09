"""app/agent/tts.py: the Kokoro voice-service HTTP client. Everything here is a
degrade-to-None contract test (per CLAUDE.md, network-dependent paths get contract
tests with stubbed responses) -- the real service is exercised manually, not here.
"""

import httpx
import pytest

from app.agent import tts


@pytest.mark.asyncio
async def test_synthesize_returns_audio_bytes_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = b"RIFF....WAVEfmt "

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/synthesize"
        return httpx.Response(200, content=expected)

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))

    result = await tts.synthesize("hello there")

    assert result == expected


@pytest.mark.asyncio
async def test_synthesize_returns_none_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))

    result = await tts.synthesize("hello there")

    assert result is None


@pytest.mark.asyncio
async def test_synthesize_returns_none_on_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))

    result = await tts.synthesize("hello there")

    assert result is None


@pytest.mark.asyncio
async def test_synthesize_returns_none_on_http_error_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"model not ready")

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))

    result = await tts.synthesize("hello there")

    assert result is None


@pytest.mark.asyncio
async def test_synthesize_skips_network_call_for_empty_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not be called for empty text")

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))

    result = await tts.synthesize("   ")

    assert result is None


_RealAsyncClient = httpx.AsyncClient


def _client_factory(handler):
    def factory(*args, **kwargs):
        kwargs.pop("timeout", None)
        return _RealAsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    return factory
