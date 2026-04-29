"""
SQLite conversation memory store with Fernet-encrypted PII columns.
Stores messages and rolling memory summaries per user.
"""

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..security.crypto import decrypt_text, encrypt_text

# IST offset for session management
IST = timezone(timedelta(hours=5, minutes=30))

# Gap between messages that triggers a new session
SESSION_GAP_HOURS = 4


def _now_iso() -> str:
    """Current time in ISO 8601 (IST)."""
    return datetime.now(IST).isoformat()


class ConversationStore:
    """
    Encrypted conversation store backed by SQLite.

    Sensitive columns (content, summary, facts) are Fernet-encrypted.
    Phone numbers are stored as SHA-256 hashes for log correlation,
    but we need the real phone for user lookup so we store it encrypted.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_tables()

    def _init_tables(self):
        """Create tables if they don't exist."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                role TEXT NOT NULL,
                content_enc TEXT NOT NULL,
                audio_path TEXT,
                timestamp TEXT NOT NULL,
                session_id TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_phone_time
                ON messages(phone, timestamp);

            CREATE TABLE IF NOT EXISTS memory (
                phone TEXT PRIMARY KEY,
                summary_enc TEXT NOT NULL,
                facts_enc TEXT NOT NULL,
                last_updated TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS nudges (
                phone TEXT NOT NULL,
                slot TEXT NOT NULL,
                last_sent TEXT NOT NULL,
                PRIMARY KEY(phone, slot)
            );
        """)
        self._conn.commit()

    def _encrypt(self, plaintext: str) -> str:
        return encrypt_text(plaintext)

    def _decrypt(self, ciphertext: str) -> str:
        return decrypt_text(ciphertext)

    # ── Session management ────────────────────────────────────────────

    def _get_last_message_time(self, phone: str) -> Optional[datetime]:
        """Get the timestamp of the last message from this user."""
        row = self._conn.execute(
            "SELECT timestamp FROM messages WHERE phone = ? ORDER BY timestamp DESC LIMIT 1",
            (phone,),
        ).fetchone()
        if row:
            return datetime.fromisoformat(row[0])
        return None

    def get_or_create_session(self, phone: str) -> Tuple[str, bool]:
        """
        Get current session ID or create a new one.

        Returns:
            (session_id, is_new_session) tuple
        """
        last_time = self._get_last_message_time(phone)
        now = datetime.now(IST)

        if last_time is None:
            # First ever message from this user
            return uuid.uuid4().hex[:12], True

        gap = now - last_time
        if gap > timedelta(hours=SESSION_GAP_HOURS):
            return uuid.uuid4().hex[:12], True

        # Same session — get the current session_id
        row = self._conn.execute(
            "SELECT session_id FROM messages WHERE phone = ? ORDER BY timestamp DESC LIMIT 1",
            (phone,),
        ).fetchone()
        return row[0] or uuid.uuid4().hex[:12], False

    # ── Message CRUD ──────────────────────────────────────────────────

    def save_message(
        self,
        phone: str,
        role: str,
        content: str,
        session_id: str,
        audio_path: Optional[str] = None,
    ) -> int:
        """Save a message with encrypted content. Returns message ID."""
        cursor = self._conn.execute(
            """INSERT INTO messages (phone, role, content_enc, audio_path, timestamp, session_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (phone, role, self._encrypt(content), audio_path, _now_iso(), session_id),
        )
        self._conn.commit()
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def get_recent_messages(self, phone: str, limit: int = 8) -> List[Dict[str, str]]:
        """Get the most recent messages for a user (decrypted)."""
        rows = self._conn.execute(
            """SELECT role, content_enc, timestamp FROM messages
               WHERE phone = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (phone, limit),
        ).fetchall()

        messages = []
        for role, content_enc, ts in reversed(rows):  # chronological order
            messages.append(
                {
                    "role": role,
                    "content": self._decrypt(content_enc),
                    "timestamp": ts,
                }
            )
        return messages

    def get_session_messages(self, phone: str, session_id: str) -> List[Dict[str, str]]:
        """Get all messages in a specific session (decrypted)."""
        rows = self._conn.execute(
            """SELECT role, content_enc, timestamp FROM messages
               WHERE phone = ? AND session_id = ?
               ORDER BY timestamp ASC""",
            (phone, session_id),
        ).fetchall()

        return [
            {"role": role, "content": self._decrypt(enc), "timestamp": ts}
            for role, enc, ts in rows
        ]

    def count_user_messages(self, phone: str) -> int:
        """Count total user (not assistant) messages for summarization trigger."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM messages WHERE phone = ? AND role = 'user'",
            (phone,),
        ).fetchone()
        return row[0]

    def is_first_ever_message(self, phone: str) -> bool:
        """Returns True if this is the user's very first message ever."""
        return self.count_user_messages(phone) == 0

    # ── Memory (rolling summary + facts) ──────────────────────────────

    def get_memory(self, phone: str) -> Optional[Dict[str, Any]]:
        """Get the rolling memory for a user (decrypted)."""
        row = self._conn.execute(
            "SELECT summary_enc, facts_enc, last_updated FROM memory WHERE phone = ?",
            (phone,),
        ).fetchone()

        if row is None:
            return None

        summary_enc, facts_enc, last_updated = row
        return {
            "summary": self._decrypt(summary_enc),
            "facts": json.loads(self._decrypt(facts_enc)),
            "last_updated": last_updated,
        }

    def save_memory(self, phone: str, summary: str, facts: List[str]) -> None:
        """Save or update the rolling memory for a user (encrypted)."""
        facts_json = json.dumps(facts, ensure_ascii=False)
        self._conn.execute(
            """INSERT INTO memory (phone, summary_enc, facts_enc, last_updated)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(phone) DO UPDATE SET
                   summary_enc = excluded.summary_enc,
                   facts_enc = excluded.facts_enc,
                   last_updated = excluded.last_updated""",
            (phone, self._encrypt(summary), self._encrypt(facts_json), _now_iso()),
        )
        self._conn.commit()

    # ── Nudge tracking (per-user, per-slot last-fired timestamps) ─────

    def record_nudge_sent(self, phone: str, slot: str) -> None:
        """Mark that a nudge for this phone+slot just went out."""
        self._conn.execute(
            """INSERT INTO nudges (phone, slot, last_sent)
               VALUES (?, ?, ?)
               ON CONFLICT(phone, slot) DO UPDATE SET last_sent = excluded.last_sent""",
            (phone, slot, _now_iso()),
        )
        self._conn.commit()

    def get_last_nudge_sent(self, phone: str, slot: str) -> Optional[datetime]:
        """When was the last nudge of this slot sent to this phone? None if never."""
        row = self._conn.execute(
            "SELECT last_sent FROM nudges WHERE phone = ? AND slot = ?",
            (phone, slot),
        ).fetchone()
        if row:
            return datetime.fromisoformat(row[0])
        return None

    def list_recently_active_phones(self, days: int = 7) -> List[str]:
        """Return phones with at least one user message in the last N days."""
        cutoff = (datetime.now(IST) - timedelta(days=days)).isoformat()
        rows = self._conn.execute(
            """SELECT DISTINCT phone FROM messages
               WHERE role = 'user' AND timestamp >= ?""",
            (cutoff,),
        ).fetchall()
        return [r[0] for r in rows]

    # ── Cleanup ───────────────────────────────────────────────────────

    def delete_old_messages(self, days: int) -> int:
        """Delete messages older than N days. Returns count deleted."""
        cutoff = (datetime.now(IST) - timedelta(days=days)).isoformat()
        cursor = self._conn.execute(
            "DELETE FROM messages WHERE timestamp < ?", (cutoff,)
        )
        self._conn.commit()
        return cursor.rowcount

    def delete_user(self, phone: str) -> Dict[str, int]:
        """Wipe all state for a single user — messages, memory, nudge tracking.

        After this call, `is_first_ever_message(phone)` returns True again
        and /start will trigger the onboarding intro on the next message.
        """
        msg_cur = self._conn.execute(
            "DELETE FROM messages WHERE phone = ?", (phone,)
        )
        mem_cur = self._conn.execute(
            "DELETE FROM memory WHERE phone = ?", (phone,)
        )
        nudge_cur = self._conn.execute(
            "DELETE FROM nudges WHERE phone = ?", (phone,)
        )
        self._conn.commit()
        return {
            "messages_deleted": msg_cur.rowcount,
            "memory_deleted": mem_cur.rowcount,
            "nudges_deleted": nudge_cur.rowcount,
        }

    def close(self):
        """Close the database connection."""
        self._conn.close()
