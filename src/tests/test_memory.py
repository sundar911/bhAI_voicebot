"""
Tests for src/bhai/memory/store.py — ConversationStore CRUD, session logic,
and encrypted memory upsert.

The conftest autouse fixture sets BHAI_ENCRYPTION_KEY so encrypt/decrypt works.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from bhai.memory.store import IST, SESSION_GAP_HOURS, ConversationStore


@pytest.fixture
def store(tmp_db):
    """Fresh ConversationStore for each test."""
    s = ConversationStore(tmp_db)
    yield s
    s.close()


# ── Message CRUD ───────────────────────────────────────────────────────


def test_save_and_retrieve_message(store):
    """Saved messages are decrypted and returned in chronological order."""
    phone = "+911234567890"
    session_id = "sess001"

    store.save_message(phone, "user", "Bhai salary kyun kata?", session_id)
    store.save_message(phone, "assistant", "Teen absence ki wajah se.", session_id)

    msgs = store.get_recent_messages(phone, limit=10)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert "salary" in msgs[0]["content"]
    assert msgs[1]["role"] == "assistant"
    assert "absence" in msgs[1]["content"]


def test_content_is_encrypted_at_rest(store, tmp_db):
    """Raw database bytes should not contain the plaintext."""
    phone = "+911234567890"
    store.save_message(phone, "user", "supersecret message", "sess1")
    store.close()

    raw = tmp_db.read_bytes()
    assert b"supersecret message" not in raw


def test_count_user_messages_excludes_assistant(store):
    """count_user_messages only counts role='user' rows."""
    phone = "+91999"
    store.save_message(phone, "user", "msg 1", "s1")
    store.save_message(phone, "assistant", "reply 1", "s1")
    store.save_message(phone, "user", "msg 2", "s1")

    assert store.count_user_messages(phone) == 2


def test_get_recent_messages_limit(store):
    """get_recent_messages respects the limit parameter."""
    phone = "+91888"
    for i in range(10):
        store.save_message(phone, "user", f"message {i}", "s1")

    msgs = store.get_recent_messages(phone, limit=4)
    assert len(msgs) == 4


# ── Session management ─────────────────────────────────────────────────


def test_first_message_creates_new_session(store):
    """First message from a user always creates a new session."""
    sid, is_new = store.get_or_create_session("+91111")
    assert is_new is True
    assert len(sid) == 12  # uuid4().hex[:12]


def test_same_session_within_gap(store):
    """Messages within SESSION_GAP_HOURS share the same session."""
    phone = "+91222"
    sid, _ = store.get_or_create_session(phone)
    store.save_message(phone, "user", "first", sid)

    sid2, is_new = store.get_or_create_session(phone)
    assert is_new is False
    assert sid2 == sid


def test_new_session_after_gap(store):
    """Messages more than SESSION_GAP_HOURS apart start a new session."""
    phone = "+91333"
    old_sid = "oldsession"

    # Save a message with a timestamp far in the past
    past_time = (datetime.now(IST) - timedelta(hours=SESSION_GAP_HOURS + 1)).isoformat()

    store._conn.execute(
        "INSERT INTO messages (phone, role, content_enc, timestamp, session_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (phone, "user", "x", past_time, old_sid),
    )
    store._conn.commit()

    new_sid, is_new = store.get_or_create_session(phone)
    assert is_new is True
    assert new_sid != old_sid


# ── Memory (rolling summary + facts) ──────────────────────────────────


def test_save_and_get_memory(store):
    """Memory save/retrieve round-trip with decryption."""
    phone = "+91444"
    store.save_memory(
        phone, "User asked about PF twice.", ["has sick child", "works night shift"]
    )

    mem = store.get_memory(phone)
    assert mem is not None
    assert "PF" in mem["summary"]
    assert "has sick child" in mem["facts"]
    assert "works night shift" in mem["facts"]


def test_memory_upsert_updates_existing(store):
    """Second save_memory call overwrites the first (ON CONFLICT upsert)."""
    phone = "+91555"
    store.save_memory(phone, "First summary.", ["fact A"])
    store.save_memory(phone, "Updated summary.", ["fact B"])

    mem = store.get_memory(phone)
    assert "Updated" in mem["summary"]
    assert mem["facts"] == ["fact B"]

    # Exactly one row in the memory table
    count = store._conn.execute(
        "SELECT COUNT(*) FROM memory WHERE phone = ?", (phone,)
    ).fetchone()[0]
    assert count == 1


def test_get_memory_returns_none_when_absent(store):
    """get_memory returns None for a user with no memory saved."""
    assert store.get_memory("+91_unknown") is None


def test_delete_old_messages(store):
    """delete_old_messages removes only messages older than the cutoff."""
    phone = "+91666"
    # Insert an old message manually
    old_ts = (datetime.now(IST) - timedelta(days=10)).isoformat()
    store._conn.execute(
        "INSERT INTO messages (phone, role, content_enc, timestamp, session_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (phone, "user", "old", old_ts, "s0"),
    )
    store._conn.commit()

    store.save_message(phone, "user", "recent", "s1")

    deleted = store.delete_old_messages(days=5)
    assert deleted == 1

    remaining = store.get_recent_messages(phone)
    assert len(remaining) == 1
    assert "recent" in remaining[0]["content"]
