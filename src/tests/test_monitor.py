"""Tests for src/bhai/proactive/monitor.py — the nudge_log reconstruction pass.

The autouse conftest fixture sets BHAI_ENCRYPTION_KEY so encrypt/decrypt works.
"""

from __future__ import annotations

import pytest

from bhai.config import load_config
from bhai.memory.store import ConversationStore
from bhai.proactive.monitor import reconstruct_nudge_log


@pytest.fixture
def store(tmp_db):
    s = ConversationStore(tmp_db)
    yield s
    s.close()


def _insert(store: ConversationStore, phone: str, role: str, content: str, ts: str):
    """Insert a message at a CONTROLLED timestamp (save_message stamps now)."""
    store._conn.execute(
        """INSERT INTO messages (phone, role, content_enc, audio_path, timestamp, session_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (phone, role, store._encrypt(content), None, ts, "s1"),
    )
    store._conn.commit()


PHONE = "abc123def456"


def _seed_scenario(store: ConversationStore):
    # 08:00 — context message, creates the >30min gap before the morning nudge
    _insert(store, PHONE, "user", "सुप्रभात भाई", "2026-06-01T08:00:00+05:30")
    # 10:05 — morning nudge (2h gap → classified as nudge), gets a reaction
    _insert(
        store,
        PHONE,
        "assistant",
        "अरे, बेटी की तबियत कैसी है अब?",
        "2026-06-01T10:05:00+05:30",
    )
    # 12:00 — user reaction to the morning nudge (within 24h)
    _insert(store, PHONE, "user", "अब ठीक है, बुखार उतर गया", "2026-06-01T12:00:00+05:30")
    # 21:10 — night nudge (9h gap → nudge), NO reaction after it
    _insert(
        store, PHONE, "assistant", "सो जाओ अब, कल मिलते हैं", "2026-06-01T21:10:00+05:30"
    )


def test_reconstruct_pairs_nudges_with_reactions(store):
    _seed_scenario(store)
    result = reconstruct_nudge_log(store, load_config(), days=365)

    assert PHONE in result
    counts = result[PHONE]
    assert counts.nudges == 2
    assert counts.with_reaction == 1
    assert counts.inserted == 2

    # nudge_log now has both, most-recent first (night, then morning).
    entries = store.recent_nudges(PHONE, days=365)
    assert len(entries) == 2
    by_slot = {e.slot: e for e in entries}
    assert by_slot["morning"].reaction == "अब ठीक है, बुखार उतर गया"
    assert by_slot["morning"].reacted_at == "2026-06-01T12:00:00+05:30"
    assert by_slot["night"].reaction is None


def test_reconstruct_excludes_reactive_replies(store):
    # A user turn immediately followed (2 min) by an assistant reply inside the
    # afternoon window is a REACTIVE reply, not a nudge — the gap is < 30min.
    _insert(store, PHONE, "user", "भाई एक बात पूछनी थी", "2026-06-02T14:00:00+05:30")
    _insert(store, PHONE, "assistant", "हाँ बोलो", "2026-06-02T14:02:00+05:30")
    result = reconstruct_nudge_log(store, load_config(), days=365)
    assert PHONE not in result  # no nudge-shaped messages at all


def test_reconstruct_is_idempotent(store):
    _seed_scenario(store)
    cfg = load_config()
    reconstruct_nudge_log(store, cfg, days=365)
    # Second run inserts nothing new; every nudge is skipped as existing.
    second = reconstruct_nudge_log(store, cfg, days=365)
    counts = second[PHONE]
    assert counts.inserted == 0
    assert counts.skipped_existing == 2
    assert len(store.recent_nudges(PHONE, days=365)) == 2


def test_reconstruct_dry_run_writes_nothing(store):
    _seed_scenario(store)
    result = reconstruct_nudge_log(store, load_config(), days=365, dry_run=True)
    assert result[PHONE].nudges == 2
    assert store.recent_nudges(PHONE, days=365) == []
