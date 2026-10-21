"""Conversation state lives here, and only here. The LLM itself is stateless
between calls - every call receives the full relevant history explicitly
assembled from this store. See docs/architecture.md "Where Application State
and Memory Reside".
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "app_state.db"
DB_PATH = Path(os.environ.get("SQLITE_PATH", str(_DEFAULT_PATH)))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS calculations (
    session_id TEXT PRIMARY KEY,
    aggregate_json TEXT NOT NULL,
    eligibility_json TEXT NOT NULL,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""
# calculations holds the REAL, structured result of the last /calculate
# call for a session - not just the human-readable text summary that goes
# into `messages`. See docs/evaluation.md Failure 15: a live model
# misread its own earlier text summary and told a student they WERE
# eligible for a category the real calculation had marked ineligible.
# Chat has no tool access to compute_aggregate/check_eligibility itself
# (Failure 6), so without this table there was no way to deterministically
# check "what did the real calculation actually say" against anything the
# model claims later in the conversation - only the text the model itself
# might misread.


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_history(session_id: str) -> list[dict]:
    """Returns messages in {"role": ..., "content": ...} form, ready to hand
    straight to the LLM client. `content` is stored as a JSON string so tool
    call arguments/results round-trip exactly; plain text messages are stored
    as a JSON-encoded string too, for one consistent decode path.
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    return [{"role": role, "content": json.loads(content)} for role, content in rows]


def append_message(session_id: str, role: str, content: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
            (session_id, role, json.dumps(content)),
        )


def reset_session(session_id: str) -> int:
    """Deletes all messages for a session. Returns the number of rows
    deleted, so "reset" is an auditable operation, not a guess.
    """
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM calculations WHERE session_id = ?", (session_id,))
        return cursor.rowcount


def set_last_calculation(session_id: str, aggregate: dict, eligibility: dict) -> None:
    """Upserts the REAL, structured result of the most recent /calculate
    call for this session - see the `calculations` table's comment in
    _SCHEMA for why this exists (Failure 15)."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO calculations (session_id, aggregate_json, eligibility_json, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(session_id) DO UPDATE SET
                aggregate_json = excluded.aggregate_json,
                eligibility_json = excluded.eligibility_json,
                updated_at = excluded.updated_at
            """,
            (session_id, json.dumps(aggregate), json.dumps(eligibility)),
        )


def get_last_calculation(session_id: str) -> dict | None:
    """Returns {"aggregate": {...}, "eligibility": {...}} for this session's
    most recent /calculate call, or None if the student hasn't used the
    "Enter My Grades" button yet this session."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT aggregate_json, eligibility_json FROM calculations WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    if row is None:
        return None
    return {"aggregate": json.loads(row[0]), "eligibility": json.loads(row[1])}
