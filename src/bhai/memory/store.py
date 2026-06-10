"""
SQLite conversation memory store with Fernet-encrypted PII columns.
Stores messages and rolling memory summaries per user.
"""

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..proactive.threads import MAX_HISTORY_ENTRIES, THREAD_STATES, Thread, ThreadPatch
from ..security.crypto import decrypt_text, encrypt_text

logger = logging.getLogger(__name__)

# IST offset for session management
IST = timezone(timedelta(hours=5, minutes=30))

# Gap between messages that triggers a new session
SESSION_GAP_HOURS = 4


def _now_iso() -> str:
    """Current time in ISO 8601 (IST)."""
    return datetime.now(IST).isoformat()


@dataclass
class NudgeLogEntry:
    """One delivered proactive nudge, plus the user's reaction if one came.

    Written by ``ConversationStore.log_nudge_delivered`` at delivery time;
    ``reaction`` / ``reacted_at`` are filled in later by
    ``record_nudge_reaction`` when the user's next message arrives inside
    the attribution window. The dossier renderer turns these rows into
    ``nudge_history.md`` — the data the anti-relentless brainstorm/critique
    prompts and the joke-dedup pass have always been told to read but never
    actually had (the file was a hardcoded placeholder before this).
    """

    phone: str
    slot: str
    category: str
    text: str
    delivered_at: str
    topic: Optional[str] = None
    reaction: Optional[str] = None
    reacted_at: Optional[str] = None
    id: Optional[int] = None


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
        self._conn.executescript(
            """
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

            CREATE TABLE IF NOT EXISTS nudge_prefs (
                phone TEXT PRIMARY KEY,
                throttle_hours INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            );

            -- v2 proactive feedback loop: the actual content of each
            -- delivered nudge + the user's reaction. Distinct from the
            -- `nudges` throttle table (which only holds per-slot
            -- last_sent timestamps). text_enc / reaction_enc are
            -- Fernet-encrypted like message content.
            CREATE TABLE IF NOT EXISTS nudge_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                slot TEXT NOT NULL,
                category TEXT NOT NULL,
                topic TEXT,
                text_enc TEXT NOT NULL,
                delivered_at TEXT NOT NULL,
                reaction_enc TEXT,
                reacted_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_nudge_log_phone_time
                ON nudge_log(phone, delivered_at);

            CREATE TABLE IF NOT EXISTS threads (
                phone TEXT NOT NULL,
                slug TEXT NOT NULL,
                state TEXT NOT NULL,
                context_enc TEXT NOT NULL,
                history_enc TEXT NOT NULL,
                opened_at TEXT NOT NULL,
                last_touched_at TEXT NOT NULL,
                last_nudged_at TEXT,
                PRIMARY KEY (phone, slug)
            );

            CREATE INDEX IF NOT EXISTS idx_threads_phone_state
                ON threads(phone, state);
            -- Append-only history of every nudge text sent, encrypted at
            -- rest. Read by the nudge prompt builder so tomorrow's nudge
            -- can avoid repeating today's topic (anti-relentless rule).
            -- Kept separate from the `nudges` table so the existing per-
            -- (phone,slot) throttle logic remains untouched.
            CREATE TABLE IF NOT EXISTS nudge_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                slot TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                text_enc TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_nudge_history_phone_time
                ON nudge_history(phone, sent_at);
        """
        )
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

    def record_nudge_text(
        self,
        phone: str,
        slot: str,
        text: str,
        *,
        at: Optional[str] = None,
    ) -> None:
        """Append a delivered nudge to `nudge_history`, encrypted at rest.

        Called by `_maybe_nudge_one` right after a successful send so the
        next firing for this user can see what's already been sent and avoid
        repeating it (Rule 4 of NUDGE_INSTRUCTION).

        `at` overrides the current-time stamp — used by the one-shot
        backfill script (scripts/backfill_nudge_history.py) to preserve
        original send timestamps when seeding the table from existing
        message history. Format: ISO 8601 string matching the timestamp
        format used elsewhere in this store.
        """
        sent_at = at if at is not None else _now_iso()
        self._conn.execute(
            """INSERT INTO nudge_history (phone, slot, sent_at, text_enc)
               VALUES (?, ?, ?, ?)""",
            (phone, slot, sent_at, self._encrypt(text)),
        )
        self._conn.commit()

    def list_nudge_history_keys(self, phone: str) -> set[tuple[str, str]]:
        """Return the (slot, sent_at) pairs already recorded for this phone.

        Used by the backfill script as a cheap idempotency check — re-runs
        skip rows already inserted on a previous pass, so the backfill is
        safe to invoke multiple times.
        """
        rows = self._conn.execute(
            "SELECT slot, sent_at FROM nudge_history WHERE phone = ?", (phone,)
        ).fetchall()
        return {(r[0], r[1]) for r in rows}

    def list_recent_nudge_texts(self, phone: str, days: int = 14) -> List[str]:
        """Return decrypted nudge texts delivered to this phone in the last
        N days, chronological. Used by the nudge prompt builder to inject
        the 'do NOT repeat these topics' list per Rule 4."""
        cutoff = (datetime.now(IST) - timedelta(days=days)).isoformat()
        rows = self._conn.execute(
            """SELECT text_enc FROM nudge_history
               WHERE phone = ? AND sent_at >= ?
               ORDER BY sent_at ASC""",
            (phone, cutoff),
        ).fetchall()
        return [self._decrypt(r[0]) for r in rows]

    def get_last_nudge_sent(self, phone: str, slot: str) -> Optional[datetime]:
        """When was the last nudge of this slot sent to this phone? None if never."""
        row = self._conn.execute(
            "SELECT last_sent FROM nudges WHERE phone = ? AND slot = ?",
            (phone, slot),
        ).fetchone()
        if row:
            return datetime.fromisoformat(row[0])
        return None

    def get_last_any_nudge_sent(self, phone: str) -> Optional[datetime]:
        """When was the most recent nudge of ANY slot sent to this phone?

        Used by per-user throttling: when a user has a `throttle_hours` override,
        we treat any nudge in either slot as the gating event.
        """
        row = self._conn.execute(
            "SELECT MAX(last_sent) FROM nudges WHERE phone = ?", (phone,)
        ).fetchone()
        if row and row[0]:
            return datetime.fromisoformat(row[0])
        return None

    def set_throttle_hours(self, phone: str, hours: int) -> None:
        """Set a per-user throttle: bhAI will only nudge this phone every N hours.

        When set, this overrides the default per-slot 18h gap. Pass `hours=0` (or
        a negative value) to clear any existing throttle for this phone.
        """
        if hours <= 0:
            self._conn.execute("DELETE FROM nudge_prefs WHERE phone = ?", (phone,))
        else:
            self._conn.execute(
                """INSERT INTO nudge_prefs (phone, throttle_hours, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(phone) DO UPDATE SET
                       throttle_hours = excluded.throttle_hours,
                       updated_at = excluded.updated_at""",
                (phone, hours, _now_iso()),
            )
        self._conn.commit()

    def get_throttle_hours(self, phone: str) -> Optional[int]:
        """Per-user throttle override in hours, or None if not set."""
        row = self._conn.execute(
            "SELECT throttle_hours FROM nudge_prefs WHERE phone = ?", (phone,)
        ).fetchone()
        if row:
            return int(row[0])
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

    # ── Nudge content log (v2 proactive feedback loop) ────────────────

    def log_nudge_delivered(
        self,
        phone: str,
        slot: str,
        *,
        category: str,
        text: str,
        topic: Optional[str] = None,
    ) -> int:
        """Append the content of a delivered nudge to ``nudge_log``.

        The write half of the proactive feedback loop. Stores the spoken
        text encrypted (it carries the user's name + personal context, same
        privacy contract as ``messages``). ``topic`` is the thread slug or a
        short label the relentlessness gate dedups on; ``None`` for jokes /
        domain-grounded nudges. Returns the new row id.
        """
        cur = self._conn.execute(
            """INSERT INTO nudge_log
                   (phone, slot, category, topic, text_enc, delivered_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (phone, slot, category, topic, self._encrypt(text), _now_iso()),
        )
        self._conn.commit()
        return int(cur.lastrowid) if cur.lastrowid is not None else -1

    def record_nudge_reaction(
        self,
        phone: str,
        reaction_text: str,
        *,
        window_hours: int = 24,
    ) -> bool:
        """Attach a user message as the reaction to their most recent
        un-reacted nudge, if one went out within ``window_hours``.

        Called from the reactive ingest on every inbound user message. Only
        the FIRST reply after a nudge attaches (the row is then non-NULL, so
        later unrelated messages can't clobber it). Returns True if a
        reaction was recorded. The read-back half of the feedback loop — the
        brainstorm pass reads these reactions to learn what actually landed.
        """
        cutoff = (datetime.now(IST) - timedelta(hours=window_hours)).isoformat()
        row = self._conn.execute(
            """SELECT id FROM nudge_log
               WHERE phone = ? AND reaction_enc IS NULL AND delivered_at >= ?
               ORDER BY delivered_at DESC LIMIT 1""",
            (phone, cutoff),
        ).fetchone()
        if not row:
            return False
        self._conn.execute(
            "UPDATE nudge_log SET reaction_enc = ?, reacted_at = ? WHERE id = ?",
            (self._encrypt(reaction_text), _now_iso(), row[0]),
        )
        self._conn.commit()
        return True

    def backfill_nudge_log(
        self,
        phone: str,
        slot: str,
        *,
        category: str,
        text: str,
        delivered_at: str,
        reaction: Optional[str] = None,
        reacted_at: Optional[str] = None,
        topic: Optional[str] = None,
    ) -> Optional[int]:
        """Idempotent historical insert for the nudge_log migration.

        Unlike ``log_nudge_delivered`` (which stamps ``_now_iso()``), this
        writes the ORIGINAL ``delivered_at`` and an optional already-known
        ``reaction``/``reacted_at`` in one shot — used by the one-off
        reconstruction that seeds nudge_log from the ``messages`` transcript
        for pilot users who pre-date the feedback loop. Skips (returns None)
        if a row with the same ``(phone, slot, delivered_at)`` already exists,
        so re-runs are safe. Returns the new row id otherwise.
        """
        exists = self._conn.execute(
            """SELECT 1 FROM nudge_log
               WHERE phone = ? AND slot = ? AND delivered_at = ? LIMIT 1""",
            (phone, slot, delivered_at),
        ).fetchone()
        if exists:
            return None
        cur = self._conn.execute(
            """INSERT INTO nudge_log
                   (phone, slot, category, topic, text_enc, delivered_at,
                    reaction_enc, reacted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                phone,
                slot,
                category,
                topic,
                self._encrypt(text),
                delivered_at,
                self._encrypt(reaction) if reaction else None,
                reacted_at,
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid) if cur.lastrowid is not None else -1

    def recent_nudges(
        self,
        phone: str,
        *,
        days: int = 30,
        limit: int = 30,
    ) -> List[NudgeLogEntry]:
        """Most-recent-first delivered nudges (with reactions) in the last N
        days. Feeds the dossier's ``nudge_history.md`` so the anti-relentless
        prompts and joke dedup finally have real data to read."""
        cutoff = (datetime.now(IST) - timedelta(days=days)).isoformat()
        rows = self._conn.execute(
            """SELECT id, phone, slot, category, topic, text_enc,
                      delivered_at, reaction_enc, reacted_at
               FROM nudge_log
               WHERE phone = ? AND delivered_at >= ?
               ORDER BY delivered_at DESC LIMIT ?""",
            (phone, cutoff, limit),
        ).fetchall()
        return [
            NudgeLogEntry(
                id=r[0],
                phone=r[1],
                slot=r[2],
                category=r[3],
                topic=r[4],
                text=self._decrypt(r[5]),
                delivered_at=r[6],
                reaction=self._decrypt(r[7]) if r[7] else None,
                reacted_at=r[8],
            )
            for r in rows
        ]

    def recent_joke_texts(self, phone: str, *, days: int = 30) -> List[str]:
        """Stripped texts of jokes delivered in the last N days — the hard
        dedup gate the joke pass seeds so the same vault joke can't fire
        twice in a month (replay finding #4: the fan/AC joke fired 5×)."""
        return [
            n.text.strip()
            for n in self.recent_nudges(phone, days=days, limit=100)
            if n.category == "joke"
        ]

    # ── Open threads (v2 proactive) ───────────────────────────────────

    def _row_to_thread(self, row: Tuple[Any, ...]) -> Thread:
        """Decrypt and hydrate a thread row into the public dataclass."""
        (
            phone,
            slug,
            state,
            context_enc,
            history_enc,
            opened_at,
            last_touched_at,
            last_nudged_at,
        ) = row
        history_raw = self._decrypt(history_enc)
        try:
            history = json.loads(history_raw) if history_raw else []
        except json.JSONDecodeError:
            # Defensive: if the encrypted blob ever decodes to something
            # other than a JSON array, surface it as empty rather than
            # crashing the proactive loop.
            logger.warning(
                "thread.history.malformed phone=%s slug=%s — resetting to empty",
                phone,
                slug,
            )
            history = []
        return Thread(
            phone=phone,
            slug=slug,
            state=state,
            context=self._decrypt(context_enc),
            history=history,
            opened_at=opened_at,
            last_touched_at=last_touched_at,
            last_nudged_at=last_nudged_at,
        )

    def get_thread(self, phone: str, slug: str) -> Optional[Thread]:
        """Fetch a single thread by (phone, slug), or None if missing."""
        row = self._conn.execute(
            """SELECT phone, slug, state, context_enc, history_enc,
                      opened_at, last_touched_at, last_nudged_at
               FROM threads WHERE phone = ? AND slug = ?""",
            (phone, slug),
        ).fetchone()
        return self._row_to_thread(row) if row else None

    def list_threads(
        self,
        phone: str,
        *,
        states: Optional[List[str]] = None,
    ) -> List[Thread]:
        """List a user's threads, optionally filtered by state.

        Without ``states``, returns every thread for the user (including
        closed ones) ordered by most-recently-touched first — useful for
        the dossier renderer which groups by state itself. With ``states``,
        returns only threads in one of the listed states.
        """
        if states is None:
            rows = self._conn.execute(
                """SELECT phone, slug, state, context_enc, history_enc,
                          opened_at, last_touched_at, last_nudged_at
                   FROM threads WHERE phone = ?
                   ORDER BY last_touched_at DESC""",
                (phone,),
            ).fetchall()
        else:
            # Build placeholders for the IN clause; SQLite has no native
            # array binding so we expand inline.
            placeholders = ",".join("?" * len(states))
            rows = self._conn.execute(
                f"""SELECT phone, slug, state, context_enc, history_enc,
                           opened_at, last_touched_at, last_nudged_at
                    FROM threads
                    WHERE phone = ? AND state IN ({placeholders})
                    ORDER BY last_touched_at DESC""",
                (phone, *states),
            ).fetchall()
        return [self._row_to_thread(r) for r in rows]

    def apply_thread_patches(
        self, phone: str, patches: List[ThreadPatch]
    ) -> Dict[str, int]:
        """Apply a batch of thread patches emitted by the reactive LLM.

        State transitions (see ``THREAD_STATES`` in
        ``bhai.proactive.threads`` for the meaning of each state):

        - ``open`` on a new slug → INSERT as ``dormant``.
        - ``open`` on a ``closed`` slug → revive as ``dormant`` (the
          user re-raised something we'd previously resolved).
        - ``open`` on a slug already in ``dormant``/``active``/
          ``do_not_nudge`` → treated as an ``update`` (the LLM lost
          track of which threads exist; auto-degrade rather than
          double-create).
        - ``update`` on a known slug → refresh context, keep state.
        - ``update`` on a missing slug → auto-promote to a new
          ``dormant`` thread (so a thinker that drafts a patch slightly
          ahead of the LLM's open-emission still persists context).
        - ``close`` on a known slug → state → ``closed``.
        - ``close`` on a missing slug → skipped (nothing to close).
        - ``mark_sensitive`` on a known slug → state → ``do_not_nudge``,
          context preserved.
        - ``mark_sensitive`` on a missing slug → INSERT as
          ``do_not_nudge`` with empty context (the agent has decided to
          steer clear of this topic before any thread record existed —
          we still want a row to prevent future nudges).

        Invalid patches (failing ``ThreadPatch.is_valid``) are logged
        and skipped without raising. Returns a counter dict:
        ``{"opened", "updated", "closed", "marked_sensitive", "skipped"}``.
        """
        counts = {
            "opened": 0,
            "updated": 0,
            "closed": 0,
            "marked_sensitive": 0,
            "skipped": 0,
        }
        for patch in patches:
            if not patch.is_valid():
                logger.warning(
                    "thread.patch.invalid op=%s topic=%s — skipped",
                    patch.op,
                    patch.topic,
                )
                counts["skipped"] += 1
                continue

            existing = self.get_thread(phone, patch.topic)
            now = _now_iso()

            if patch.op == "open":
                if existing is None:
                    self._insert_thread(
                        phone=phone,
                        slug=patch.topic,
                        state="dormant",
                        context=patch.context,
                        history=[{"ts": now, "op": "open", "context": patch.context}],
                        opened_at=now,
                        last_touched_at=now,
                    )
                    counts["opened"] += 1
                elif existing.state == "closed":
                    history = self._append_history(
                        existing.history, now, "open", patch.context
                    )
                    self._update_thread(
                        phone=phone,
                        slug=patch.topic,
                        state="dormant",
                        context=patch.context,
                        history=history,
                        last_touched_at=now,
                    )
                    counts["opened"] += 1
                else:
                    # Slug already live — treat as update to avoid
                    # silently dropping the LLM's new context.
                    history = self._append_history(
                        existing.history, now, "update", patch.context
                    )
                    self._update_thread(
                        phone=phone,
                        slug=patch.topic,
                        state=existing.state,
                        context=patch.context,
                        history=history,
                        last_touched_at=now,
                    )
                    counts["updated"] += 1
                    logger.info(
                        "thread.open.already_active phone=%s slug=%s "
                        "state=%s — treated as update",
                        phone,
                        patch.topic,
                        existing.state,
                    )

            elif patch.op == "update":
                if existing is None:
                    # Auto-promote: the agent referenced a slug the
                    # LLM hadn't formally opened yet. Better to persist
                    # the context than to lose it.
                    self._insert_thread(
                        phone=phone,
                        slug=patch.topic,
                        state="dormant",
                        context=patch.context,
                        history=[{"ts": now, "op": "update", "context": patch.context}],
                        opened_at=now,
                        last_touched_at=now,
                    )
                    counts["opened"] += 1
                    logger.info(
                        "thread.update.missing_slug phone=%s slug=%s "
                        "— auto-promoted to dormant",
                        phone,
                        patch.topic,
                    )
                else:
                    history = self._append_history(
                        existing.history, now, "update", patch.context
                    )
                    self._update_thread(
                        phone=phone,
                        slug=patch.topic,
                        state=existing.state,
                        context=patch.context,
                        history=history,
                        last_touched_at=now,
                    )
                    counts["updated"] += 1

            elif patch.op == "close":
                if existing is None:
                    logger.info(
                        "thread.close.missing_slug phone=%s slug=%s " "— skipped",
                        phone,
                        patch.topic,
                    )
                    counts["skipped"] += 1
                else:
                    history = self._append_history(
                        existing.history, now, "close", patch.context
                    )
                    self._update_thread(
                        phone=phone,
                        slug=patch.topic,
                        state="closed",
                        context=patch.context,
                        history=history,
                        last_touched_at=now,
                    )
                    counts["closed"] += 1

            elif patch.op == "mark_sensitive":
                if existing is None:
                    self._insert_thread(
                        phone=phone,
                        slug=patch.topic,
                        state="do_not_nudge",
                        context="",
                        history=[{"ts": now, "op": "mark_sensitive", "context": ""}],
                        opened_at=now,
                        last_touched_at=now,
                    )
                    counts["marked_sensitive"] += 1
                else:
                    history = self._append_history(
                        existing.history, now, "mark_sensitive", ""
                    )
                    self._update_thread(
                        phone=phone,
                        slug=patch.topic,
                        state="do_not_nudge",
                        context=existing.context,
                        history=history,
                        last_touched_at=now,
                    )
                    counts["marked_sensitive"] += 1

        self._conn.commit()
        return counts

    def _append_history(
        self,
        prior: List[Dict[str, str]],
        ts: str,
        op: str,
        context: str,
    ) -> List[Dict[str, str]]:
        """Append a history entry and trim to MAX_HISTORY_ENTRIES."""
        prior = list(prior) + [{"ts": ts, "op": op, "context": context}]
        if len(prior) > MAX_HISTORY_ENTRIES:
            prior = prior[-MAX_HISTORY_ENTRIES:]
        return prior

    def _insert_thread(
        self,
        *,
        phone: str,
        slug: str,
        state: str,
        context: str,
        history: List[Dict[str, str]],
        opened_at: str,
        last_touched_at: str,
    ) -> None:
        """Raw INSERT — caller validates state and slug."""
        assert state in THREAD_STATES, f"unknown state: {state}"
        self._conn.execute(
            """INSERT INTO threads (phone, slug, state, context_enc,
                                    history_enc, opened_at, last_touched_at,
                                    last_nudged_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, NULL)""",
            (
                phone,
                slug,
                state,
                self._encrypt(context),
                self._encrypt(json.dumps(history, ensure_ascii=False)),
                opened_at,
                last_touched_at,
            ),
        )

    def _update_thread(
        self,
        *,
        phone: str,
        slug: str,
        state: str,
        context: str,
        history: List[Dict[str, str]],
        last_touched_at: str,
    ) -> None:
        """Raw UPDATE — caller validates state. Does NOT touch
        ``opened_at`` or ``last_nudged_at``."""
        assert state in THREAD_STATES, f"unknown state: {state}"
        self._conn.execute(
            """UPDATE threads
               SET state = ?, context_enc = ?, history_enc = ?,
                   last_touched_at = ?
               WHERE phone = ? AND slug = ?""",
            (
                state,
                self._encrypt(context),
                self._encrypt(json.dumps(history, ensure_ascii=False)),
                last_touched_at,
                phone,
                slug,
            ),
        )

    def record_nudge_outcome(
        self,
        phone: str,
        slot: str,
        thread_slug: Optional[str] = None,
        *,
        category: Optional[str] = None,
        text: Optional[str] = None,
    ) -> None:
        """Atomic post-delivery hook the nudge schedulers call after a
        successful send.

        Wraps the two state mutations a delivered nudge produces:
          - ``record_nudge_sent`` — bumps the per-slot last-sent
            timestamp (existing v1.5 throttle gate).
          - ``mark_thread_nudged`` — transitions the targeted thread
            from ``dormant`` to ``active`` (v2 piece D).

        ``thread_slug=None`` is normal — the v1.5 nudge path doesn't
        choose a thread, and the v2 thinker leaves it ``None`` when the
        candidate is grounded in a domain-file fact rather than an open
        thread. In both cases we still need to record the send.

        When ``category`` and ``text`` are both supplied the nudge content
        is also appended to ``nudge_log`` (the feedback loop). Callers that
        only have a bare send (legacy admin pings) can omit them and just
        get the throttle + thread-state bump as before.
        """
        self.record_nudge_sent(phone, slot)
        if thread_slug:
            self.mark_thread_nudged(phone, thread_slug)
        if category is not None and text is not None:
            self.log_nudge_delivered(
                phone, slot, category=category, text=text, topic=thread_slug
            )

    def mark_thread_nudged(self, phone: str, slug: str) -> bool:
        """Stamp ``last_nudged_at`` and transition ``dormant → active``.

        Called by the proactive thinker (piece D) after it fires a nudge
        that references a specific thread. Returns True if the row was
        found and updated, False if the slug doesn't exist for this user.

        - ``dormant`` → ``active`` (we just nudged; watch for reaction).
        - ``active``/``closed``/``do_not_nudge`` → state unchanged but
          ``last_nudged_at`` still refreshed, so the thinker has an
          accurate "I touched this on day N" signal regardless.
        """
        existing = self.get_thread(phone, slug)
        if existing is None:
            logger.warning(
                "thread.mark_nudged.missing_slug phone=%s slug=%s",
                phone,
                slug,
            )
            return False
        new_state = "active" if existing.state == "dormant" else existing.state
        now = _now_iso()
        self._conn.execute(
            """UPDATE threads
               SET state = ?, last_nudged_at = ?
               WHERE phone = ? AND slug = ?""",
            (new_state, now, phone, slug),
        )
        self._conn.commit()
        return True

    # ── Cleanup ───────────────────────────────────────────────────────

    def delete_old_messages(self, days: int) -> int:
        """Delete messages older than N days. Returns count deleted."""
        cutoff = (datetime.now(IST) - timedelta(days=days)).isoformat()
        cursor = self._conn.execute(
            "DELETE FROM messages WHERE timestamp < ?", (cutoff,)
        )
        self._conn.commit()
        return cursor.rowcount

    def merge_user(self, from_phone: str, to_phone: str) -> Dict[str, int]:
        """Move all data from `from_phone` to `to_phone` (Twilio → Telegram migration).

        After this call, `from_phone` has no rows anywhere and `to_phone` owns
        the merged history, memory, and nudge tracking. Existing rows under
        `to_phone` are dropped first to avoid PRIMARY KEY conflicts on
        memory and nudges — assumes the target is empty (e.g. just /start'd).
        """
        if from_phone == to_phone:
            return {
                "messages_migrated": 0,
                "memory_migrated": 0,
                "nudges_migrated": 0,
                "threads_migrated": 0,
            }

        msg_cur = self._conn.execute(
            "UPDATE messages SET phone = ? WHERE phone = ?",
            (to_phone, from_phone),
        )
        # Memory has phone as PRIMARY KEY — clear target before re-pointing source.
        self._conn.execute("DELETE FROM memory WHERE phone = ?", (to_phone,))
        mem_cur = self._conn.execute(
            "UPDATE memory SET phone = ? WHERE phone = ?",
            (to_phone, from_phone),
        )
        # Nudges has (phone, slot) as composite PRIMARY KEY — same fix.
        self._conn.execute("DELETE FROM nudges WHERE phone = ?", (to_phone,))
        nudge_cur = self._conn.execute(
            "UPDATE nudges SET phone = ? WHERE phone = ?",
            (to_phone, from_phone),
        )
        # Threads has (phone, slug) as composite PRIMARY KEY — same fix.
        self._conn.execute("DELETE FROM threads WHERE phone = ?", (to_phone,))
        thread_cur = self._conn.execute(
            "UPDATE threads SET phone = ? WHERE phone = ?",
            (to_phone, from_phone),
        )
        # nudge_history and nudge_log are append-only with surrogate ids —
        # straight UPDATE, no pre-clear needed.
        self._conn.execute(
            "UPDATE nudge_history SET phone = ? WHERE phone = ?",
            (to_phone, from_phone),
        )
        self._conn.execute(
            "UPDATE nudge_log SET phone = ? WHERE phone = ?",
            (to_phone, from_phone),
        )
        self._conn.commit()
        return {
            "messages_migrated": msg_cur.rowcount,
            "memory_migrated": mem_cur.rowcount,
            "nudges_migrated": nudge_cur.rowcount,
            "threads_migrated": thread_cur.rowcount,
        }

    def delete_user(self, phone: str) -> Dict[str, int]:
        """Wipe all state for a single user — messages, memory, nudge tracking.

        After this call, `is_first_ever_message(phone)` returns True again
        and /start will trigger the onboarding intro on the next message.
        """
        msg_cur = self._conn.execute("DELETE FROM messages WHERE phone = ?", (phone,))
        mem_cur = self._conn.execute("DELETE FROM memory WHERE phone = ?", (phone,))
        nudge_cur = self._conn.execute("DELETE FROM nudges WHERE phone = ?", (phone,))
        thread_cur = self._conn.execute("DELETE FROM threads WHERE phone = ?", (phone,))
        # Also wipe the append-only nudge_history + nudge_log rows — privacy
        # (nudge_log holds Fernet-encrypted nudge text and reactions).
        self._conn.execute("DELETE FROM nudge_history WHERE phone = ?", (phone,))
        self._conn.execute("DELETE FROM nudge_log WHERE phone = ?", (phone,))
        self._conn.commit()
        return {
            "messages_deleted": msg_cur.rowcount,
            "memory_deleted": mem_cur.rowcount,
            "nudges_deleted": nudge_cur.rowcount,
            "threads_deleted": thread_cur.rowcount,
        }

    def close(self):
        """Close the database connection."""
        self._conn.close()
