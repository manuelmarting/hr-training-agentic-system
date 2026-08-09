"""SQLite schema for the agent's persistence layer (PRD §6.1, §7).

Four tables: T2 (learner model — per-employee, per-KC mastery), T3 (personal facts,
subject to the PII gate's view/delete right), T4 (episodic archive — immutable
session-summary rows), and `events` (the replayable turn-by-turn log auditability is
built on). `repo.py` is the only module that writes SQL against this schema.
"""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS learner_model (
    employee_id TEXT NOT NULL,
    kc_id       TEXT NOT NULL,
    mastery     REAL NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (employee_id, kc_id)
);

CREATE TABLE IF NOT EXISTS personal_facts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    fact_type   TEXT NOT NULL,
    value       TEXT NOT NULL,
    confidence  REAL NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS episodic_archive (
    session_id  TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL,
    summary     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    turn_index  INTEGER NOT NULL,
    event_type  TEXT NOT NULL,
    payload     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_session ON events (session_id, id);
CREATE INDEX IF NOT EXISTS idx_personal_facts_employee ON personal_facts (employee_id);
"""


def connect(db_path: str | Path = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
