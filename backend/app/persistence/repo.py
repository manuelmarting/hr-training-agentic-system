"""Repository over the persistence schema (`db.py`). No raw SQL outside this module.

Every turn's structured record is persisted through here before the next turn
proceeds (CLAUDE.md), and the `events` table is what `replay()` reconstructs mastery
from — the auditability requirement in PRD §7.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from app.persistence.db import connect
from app.schemas.extraction import PersonalFact, SessionSummary


class StoredFact(BaseModel):
    """A `PersonalFact` as persisted — adds the identity/timestamp needed for
    the employee's view/delete right (PRD §7)."""

    id: int
    employee_id: str
    fact: PersonalFact
    created_at: str


class EventRecord(BaseModel):
    session_id: str
    turn_index: int
    event_type: str
    payload: dict
    created_at: str


class FactNotFoundError(KeyError):
    """Raised when a fact id has no row."""


class Repo:
    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._conn: sqlite3.Connection = connect(db_path)
        self._lock = threading.Lock()

    def close(self) -> None:
        self._conn.close()

    # T2 — learner model -----------------------------------------------------

    def upsert_mastery(self, employee_id: str, kc_id: str, mastery: float) -> None:
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO learner_model (employee_id, kc_id, mastery, updated_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(employee_id, kc_id) DO UPDATE SET "
                "mastery = excluded.mastery, updated_at = excluded.updated_at",
                (employee_id, kc_id, mastery, now),
            )
            self._conn.commit()

    def get_mastery(self, employee_id: str) -> dict[str, float]:
        rows = self._conn.execute(
            "SELECT kc_id, mastery FROM learner_model WHERE employee_id = ?", (employee_id,)
        ).fetchall()
        return {row["kc_id"]: row["mastery"] for row in rows}

    # T3 — personal facts ------------------------------------------------------

    def add_fact(self, employee_id: str, fact: PersonalFact) -> StoredFact:
        now = _now()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO personal_facts "
                "(employee_id, fact_type, value, confidence, created_at) VALUES (?, ?, ?, ?, ?)",
                (employee_id, fact.fact_type, fact.value, fact.confidence, now),
            )
            self._conn.commit()
        return StoredFact(id=cur.lastrowid, employee_id=employee_id, fact=fact, created_at=now)

    def list_facts(self, employee_id: str) -> list[StoredFact]:
        rows = self._conn.execute(
            "SELECT id, employee_id, fact_type, value, confidence, created_at "
            "FROM personal_facts WHERE employee_id = ? ORDER BY id",
            (employee_id,),
        ).fetchall()
        return [
            StoredFact(
                id=row["id"],
                employee_id=row["employee_id"],
                fact=PersonalFact(
                    fact_type=row["fact_type"], value=row["value"], confidence=row["confidence"]
                ),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def delete_fact(self, fact_id: int) -> None:
        with self._lock:
            cur = self._conn.execute("DELETE FROM personal_facts WHERE id = ?", (fact_id,))
            self._conn.commit()
        if cur.rowcount == 0:
            raise FactNotFoundError(fact_id)

    # T4 — episodic archive ----------------------------------------------------

    def archive_session(self, employee_id: str, summary: SessionSummary) -> None:
        """Write the immutable session-summary audit row. Raises on re-archive of
        the same session — the archive is write-once by design."""
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO episodic_archive (session_id, employee_id, summary, created_at) "
                "VALUES (?, ?, ?, ?)",
                (summary.session_id, employee_id, summary.model_dump_json(), now),
            )
            self._conn.commit()

    def get_archived_session(self, session_id: str) -> SessionSummary | None:
        row = self._conn.execute(
            "SELECT summary FROM episodic_archive WHERE session_id = ?", (session_id,)
        ).fetchone()
        return SessionSummary.model_validate_json(row["summary"]) if row else None

    # events ---------------------------------------------------------------

    def append_event(
        self, session_id: str, turn_index: int, event_type: str, payload: dict
    ) -> None:
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO events (session_id, turn_index, event_type, payload, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, turn_index, event_type, json.dumps(payload), now),
            )
            self._conn.commit()

    def list_events(self, session_id: str) -> list[EventRecord]:
        rows = self._conn.execute(
            "SELECT session_id, turn_index, event_type, payload, created_at "
            "FROM events WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        return [
            EventRecord(
                session_id=row["session_id"],
                turn_index=row["turn_index"],
                event_type=row["event_type"],
                payload=json.loads(row["payload"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]


def _now() -> str:
    return datetime.now(UTC).isoformat()
