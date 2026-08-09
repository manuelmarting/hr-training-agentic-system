import pytest
from fastapi.testclient import TestClient

from app.agent import runtime
from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_streams_echo(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force the EchoAgent fallback deterministically — this must hold regardless of
    # whether the developer's local .env happens to have a real ANTHROPIC_API_KEY.
    async def _no_graph() -> None:
        return None

    monkeypatch.setattr(runtime, "get_compiled_graph", _no_graph)

    with client.stream(
        "POST",
        "/api/chat",
        json={"messages": [{"role": "user", "content": "hello world"}]},
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    assert "hello" in body
    assert "world" in body
