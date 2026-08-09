from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_env: str = "development"
    cors_origins: list[str] = ["http://localhost:5173"]
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None
    openai_api_key: str | None = None

    # Studio (KG-authoring, PRD §8)
    studio_db_path: Path = Path("studio.db")
    graph_output_dir: Path = Path("app/kg/generated")

    # LLM (extraction, workflow 1 conversation core). "gemini" is the default provider
    # (cheapest agentic-capable model available); "anthropic" remains fully wired as
    # the alternate. Both models below are high-volume, low-per-call-complexity
    # classification/extraction tasks (turn grading, fact extraction, KC/edge proposals
    # from a single SOP span), not open-ended generation, so the cheapest tier per
    # provider is worth taking over the larger models.
    llm_provider: str = "gemini"
    extraction_model: str = "claude-haiku-4-5-20251001"
    # gemini-2.5-flash-lite returns 404 for new API keys (2.x line closed to new users
    # as of 2026); gemini-3.5-flash-lite is the current cheapest agentic-capable model.
    gemini_extraction_model: str = "gemini-3.1-flash-lite"
    openai_extraction_model: str = "gpt-4o-mini"
    extraction_max_tokens: int = 8000
    extraction_max_concurrency: int = 4

    # Conversation core runtime (workflow 1)
    runtime_db_path: Path = Path("runtime.db")
    checkpoint_db_path: Path = Path("checkpoints.sqlite")
    mastery_threshold: float = 0.7

    # Voice output (Kokoro TTS service, standalone under voice-service/). Best-effort
    # side output of a chat turn, not part of the graph — a slow/unreachable service
    # must never block or fail a turn, see app/agent/tts.py.
    kokoro_service_url: str = "http://localhost:8001"
    kokoro_timeout_s: float = 15.0


settings = Settings()
