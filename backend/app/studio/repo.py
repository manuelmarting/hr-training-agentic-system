"""Draft persistence (plan §1): one SQLite row per draft, the draft stored as a JSON blob.

Drafts are edited wholesale by a single reviewer, so there is no concurrency to model
beyond guarding writes with a lock. The runtime graph file is only ever produced from a
draft that reaches `approved` here and then passes `materialize.py`.

Synchronous by design — FastAPI routes call these off the event loop via
`run_in_executor`. Every write goes through a method; no raw SQL leaks into the routes.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from app.studio.schemas import DraftStatus, GraphDraft

_SCHEMA = """
CREATE TABLE IF NOT EXISTS graph_drafts (
    draft_id   TEXT PRIMARY KEY,
    status     TEXT NOT NULL,
    data       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class DraftNotFoundError(KeyError):
    """Raised when a draft id has no row."""


class DraftRepo:
    """CRUD over the `graph_drafts` table. Pass `:memory:` in tests."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._conn = sqlite3.connect(
            str(db_path), check_same_thread=False, detect_types=sqlite3.PARSE_DECLTYPES
        )
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # writes ----------------------------------------------------------------

    def create(self, draft: GraphDraft) -> GraphDraft:
        """Insert a new draft. Raises if the id already exists."""
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO graph_drafts (draft_id, status, data, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (draft.draft_id, draft.status.value, draft.model_dump_json(), now, now),
            )
            self._conn.commit()
        return draft

    def save(self, draft: GraphDraft) -> GraphDraft:
        """Upsert the whole draft, refreshing `status` and `updated_at`."""
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO graph_drafts (draft_id, status, data, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(draft_id) DO UPDATE SET "
                "status = excluded.status, data = excluded.data, updated_at = excluded.updated_at",
                (draft.draft_id, draft.status.value, draft.model_dump_json(), now, now),
            )
            self._conn.commit()
        return draft

    def set_status(self, draft_id: str, status: DraftStatus) -> GraphDraft:
        """Transition a draft's status (also mirrored inside the stored blob)."""
        draft = self.get(draft_id)
        draft.status = status
        return self.save(draft)

    def delete(self, draft_id: str) -> None:
        with self._lock:
            cur = self._conn.execute("DELETE FROM graph_drafts WHERE draft_id = ?", (draft_id,))
            self._conn.commit()
        if cur.rowcount == 0:
            raise DraftNotFoundError(draft_id)

    # reads -----------------------------------------------------------------

    def get(self, draft_id: str) -> GraphDraft:
        row = self._conn.execute(
            "SELECT data FROM graph_drafts WHERE draft_id = ?", (draft_id,)
        ).fetchone()
        if row is None:
            raise DraftNotFoundError(draft_id)
        return GraphDraft.model_validate_json(row["data"])

    def get_or_none(self, draft_id: str) -> GraphDraft | None:
        try:
            return self.get(draft_id)
        except DraftNotFoundError:
            return None

    def list_drafts(self) -> list[GraphDraft]:
        """All drafts, newest-updated first."""
        rows = self._conn.execute(
            "SELECT data FROM graph_drafts ORDER BY updated_at DESC, draft_id"
        ).fetchall()
        return [GraphDraft.model_validate_json(r["data"]) for r in rows]


def _now() -> str:
    return datetime.now(UTC).isoformat()
