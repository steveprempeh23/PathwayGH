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
"""


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(_SCHEMA)
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
        return cursor.rowcount
