"""
SQLite-backed request queue for failed pipeline requests.

When an API call fails after retries, the request is persisted here
so a background worker can retry it later. Stage tracking ensures
we resume from where we left off (e.g., skip STT if transcript exists).
"""

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("bhai.resilience.queue")

# IST offset (consistent with conversation store)
IST = timezone(timedelta(hours=5, minutes=30))

# Twilio WhatsApp message window
TWILIO_WINDOW_HOURS = 23


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def _backoff_seconds(attempt: int) -> int:
    """Exponential backoff: 30s, 60s, 120s, 240s, ... capped at 30min."""
    return min(30 * (2**attempt), 1800)


class RequestQueue:
    """
    Persistent queue for failed voice-note processing requests.

    Each request tracks which pipeline stage it reached, so retries
    skip already-completed stages (e.g., don't re-run STT if we
    already have the transcript).
    """

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.row_factory = sqlite3.Row
        self._init_table()

    def _init_table(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS pending_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                sender TEXT NOT NULL,
                audio_path TEXT NOT NULL,
                stage TEXT NOT NULL,
                transcript TEXT,
                llm_response TEXT,
                domain TEXT DEFAULT 'hr_admin',
                attempt_count INTEGER DEFAULT 0,
                max_attempts INTEGER DEFAULT 5,
                next_retry_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_error TEXT,
                status TEXT DEFAULT 'pending'
            );

            CREATE INDEX IF NOT EXISTS idx_pending_status_retry
                ON pending_requests(status, next_retry_at);
        """)
        self._conn.commit()

    def enqueue(
        self,
        phone: str,
        sender: str,
        audio_path: str,
        stage: str,
        domain: str = "hr_admin",
        transcript: Optional[str] = None,
        llm_response: Optional[str] = None,
    ) -> int:
        """
        Add a failed request to the queue.

        Args:
            phone: User phone number (without whatsapp: prefix)
            sender: Full Twilio sender string (whatsapp:+91...)
            audio_path: Path to downloaded audio file
            stage: Pipeline stage to resume from ('stt', 'llm', 'tts')
            domain: Knowledge domain
            transcript: Saved transcript if STT succeeded
            llm_response: Saved LLM response if LLM succeeded

        Returns:
            The row ID of the queued request.
        """
        now = _now_iso()
        next_retry = (
            datetime.now(IST) + timedelta(seconds=_backoff_seconds(0))
        ).isoformat()

        cursor = self._conn.execute(
            """INSERT INTO pending_requests
               (phone, sender, audio_path, stage, transcript, llm_response,
                domain, next_retry_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                phone,
                sender,
                audio_path,
                stage,
                transcript,
                llm_response,
                domain,
                next_retry,
                now,
            ),
        )
        self._conn.commit()
        assert cursor.lastrowid is not None
        row_id: int = cursor.lastrowid
        logger.info(
            "Queued request id=%d stage=%s for phone hash=%s",
            row_id,
            stage,
            hash(phone) % 10000,
        )
        return row_id

    def dequeue_ready(self) -> Optional[dict]:
        """
        Pop one request that's ready for retry.

        Returns None if no requests are due. Marks the returned
        request as 'processing' to prevent double-pickup.
        """
        now = _now_iso()
        row = self._conn.execute(
            """SELECT * FROM pending_requests
               WHERE status = 'pending' AND next_retry_at <= ?
               ORDER BY next_retry_at ASC LIMIT 1""",
            (now,),
        ).fetchone()

        if row is None:
            return None

        self._conn.execute(
            "UPDATE pending_requests SET status = 'processing' WHERE id = ?",
            (row["id"],),
        )
        self._conn.commit()
        return dict(row)

    def mark_completed(self, request_id: int):
        """Mark a request as successfully processed."""
        self._conn.execute(
            "UPDATE pending_requests SET status = 'completed' WHERE id = ?",
            (request_id,),
        )
        self._conn.commit()
        logger.info("Request id=%d completed", request_id)

    def mark_failed(self, request_id: int, error_msg: str) -> bool:
        """
        Record a retry failure. Returns True if request is now dead
        (all attempts exhausted or past Twilio 24h window).
        """
        row = self._conn.execute(
            "SELECT attempt_count, max_attempts, created_at FROM pending_requests WHERE id = ?",
            (request_id,),
        ).fetchone()

        if row is None:
            return True

        new_count = row["attempt_count"] + 1
        created = datetime.fromisoformat(row["created_at"])
        age_hours = (datetime.now(IST) - created).total_seconds() / 3600

        # Dead: exhausted attempts or past Twilio window
        if new_count >= row["max_attempts"] or age_hours >= TWILIO_WINDOW_HOURS:
            self._conn.execute(
                """UPDATE pending_requests
                   SET status = 'dead', attempt_count = ?, last_error = ?
                   WHERE id = ?""",
                (new_count, error_msg, request_id),
            )
            self._conn.commit()
            logger.warning(
                "Request id=%d is dead after %d attempts", request_id, new_count
            )
            return True

        next_retry = (
            datetime.now(IST) + timedelta(seconds=_backoff_seconds(new_count))
        ).isoformat()

        self._conn.execute(
            """UPDATE pending_requests
               SET status = 'pending', attempt_count = ?, last_error = ?,
                   next_retry_at = ?
               WHERE id = ?""",
            (new_count, error_msg, next_retry, request_id),
        )
        self._conn.commit()
        logger.info(
            "Request id=%d failed attempt %d, next retry at %s",
            request_id,
            new_count,
            next_retry,
        )
        return False

    def update_stage(
        self,
        request_id: int,
        stage: str,
        transcript: Optional[str] = None,
        llm_response: Optional[str] = None,
    ):
        """Update partial progress so retries resume from the right stage."""
        updates = ["stage = ?"]
        params: list = [stage]

        if transcript is not None:
            updates.append("transcript = ?")
            params.append(transcript)
        if llm_response is not None:
            updates.append("llm_response = ?")
            params.append(llm_response)

        params.append(request_id)
        self._conn.execute(
            f"UPDATE pending_requests SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        self._conn.commit()

    def cleanup_completed(self, older_than_hours: int = 24):
        """Remove completed/dead requests older than N hours."""
        cutoff = (datetime.now(IST) - timedelta(hours=older_than_hours)).isoformat()
        cursor = self._conn.execute(
            """DELETE FROM pending_requests
               WHERE status IN ('completed', 'dead') AND created_at < ?""",
            (cutoff,),
        )
        self._conn.commit()
        if cursor.rowcount:
            logger.info("Cleaned up %d old queue entries", cursor.rowcount)

    def close(self):
        self._conn.close()
