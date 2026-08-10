from typing import Literal

from pydantic import BaseModel

from app.agent.state import Language


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    # Session continuity: omit on the first turn, echo back the `session` event's
    # `session_id` on every turn after (mirrors `agent/orchestrator.py`'s thread_id contract).
    session_id: str | None = None
    employee_id: str = "demo-employee"
    language: Language = "en"
    # True for the one request that opens a brand-new session (empty `messages`) so
    # Sofía speaks first instead of waiting on the employee. Ignored by `/api/chat` on
    # a session that already has checkpointed state, so a reconnect can't replay it.
    is_session_open: bool = False
