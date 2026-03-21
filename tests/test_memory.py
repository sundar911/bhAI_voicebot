"""
Tests for ConversationStore (SQLite + Fernet encryption) and
summarizer utility functions.

No external services required — all tests use tmp_path SQLite databases.
"""

from datetime import datetime, timedelta, timezone

import pytest

IST = timezone(timedelta(hours=5, minutes=30))
TEST_PHONE = "+919876543210"
TEST_SESSION = "abc123def456"


# ── ConversationStore ─────────────────────────────────────────────────────

def test_save_and_get_message(tmp_store):
    tmp_store.save_message(TEST_PHONE, "user", "Meri salary kyun kata?", TEST_SESSION)

    messages = tmp_store.get_recent_messages(TEST_PHONE)
    assert len(messages) == 1
    assert messages[0]["content"] == "Meri salary kyun kata?"
    assert messages[0]["role"] == "user"


def test_message_content_is_encrypted_at_rest(tmp_store):
    plaintext = "Very sensitive salary information here"
    tmp_store.save_message(TEST_PHONE, "user", plaintext, TEST_SESSION)

    # Read the raw stored value directly from SQLite
    raw = tmp_store._conn.execute(
        "SELECT content_enc FROM messages WHERE phone = ?", (TEST_PHONE,)
    ).fetchone()[0]

    # The stored value must NOT be the plaintext
    assert plaintext not in raw
    # Fernet tokens are base64 and significantly longer than the original
    assert len(raw) > len(plaintext)


def test_get_recent_messages_in_chronological_order(tmp_store):
    for i, role in enumerate(["user", "assistant", "user"]):
        tmp_store.save_message(TEST_PHONE, role, f"Message {i}", TEST_SESSION)

    messages = tmp_store.get_recent_messages(TEST_PHONE)
    assert len(messages) == 3
    assert messages[0]["content"] == "Message 0"
    assert messages[1]["content"] == "Message 1"
    assert messages[2]["content"] == "Message 2"


def test_get_recent_messages_respects_limit(tmp_store):
    for i in range(10):
        tmp_store.save_message(TEST_PHONE, "user", f"Msg {i}", TEST_SESSION)

    messages = tmp_store.get_recent_messages(TEST_PHONE, limit=4)
    assert len(messages) == 4
    # Limit returns the most recent N, in chronological order
    assert messages[-1]["content"] == "Msg 9"


def test_new_session_for_first_message(tmp_store):
    _, is_new = tmp_store.get_or_create_session(TEST_PHONE)
    assert is_new is True


def test_same_session_within_gap(tmp_store):
    sid, _ = tmp_store.get_or_create_session(TEST_PHONE)
    tmp_store.save_message(TEST_PHONE, "user", "Hello", sid)

    sid2, is_new = tmp_store.get_or_create_session(TEST_PHONE)
    assert is_new is False
    assert sid2 == sid


def test_new_session_after_gap(tmp_store):
    # Insert a message with a timestamp 5 hours ago (beyond the 4h gap)
    old_ts = (datetime.now(IST) - timedelta(hours=5)).isoformat()
    tmp_store._conn.execute(
        "INSERT INTO messages (phone, role, content_enc, timestamp, session_id) VALUES (?, ?, ?, ?, ?)",
        (TEST_PHONE, "user", "old_enc_value", old_ts, "old_session_xyz"),
    )
    tmp_store._conn.commit()

    _, is_new = tmp_store.get_or_create_session(TEST_PHONE)
    assert is_new is True


def test_save_and_get_memory(tmp_store):
    summary = "Yashoda production team mein hai. Pichle mahine 3 absences thi."
    facts = ["Bachcha beemar tha", "Salary kata tha"]

    tmp_store.save_memory(TEST_PHONE, summary, facts)

    memory = tmp_store.get_memory(TEST_PHONE)
    assert memory is not None
    assert memory["summary"] == summary
    assert "Bachcha beemar tha" in memory["facts"]
    assert "Salary kata tha" in memory["facts"]


def test_save_memory_upserts_existing(tmp_store):
    tmp_store.save_memory(TEST_PHONE, "Old summary", ["old fact"])
    tmp_store.save_memory(TEST_PHONE, "New summary", ["new fact"])

    memory = tmp_store.get_memory(TEST_PHONE)
    assert memory["summary"] == "New summary"
    assert "new fact" in memory["facts"]
    assert "old fact" not in memory["facts"]


def test_get_memory_returns_none_when_absent(tmp_store):
    assert tmp_store.get_memory("+910000000000") is None


def test_count_user_messages(tmp_store):
    tmp_store.save_message(TEST_PHONE, "user", "msg 1", TEST_SESSION)
    tmp_store.save_message(TEST_PHONE, "assistant", "reply 1", TEST_SESSION)
    tmp_store.save_message(TEST_PHONE, "user", "msg 2", TEST_SESSION)
    tmp_store.save_message(TEST_PHONE, "assistant", "reply 2", TEST_SESSION)
    tmp_store.save_message(TEST_PHONE, "user", "msg 3", TEST_SESSION)

    assert tmp_store.count_user_messages(TEST_PHONE) == 3


def test_count_messages_ignores_other_phones(tmp_store):
    tmp_store.save_message(TEST_PHONE, "user", "msg", TEST_SESSION)
    tmp_store.save_message("+910000000001", "user", "other msg", TEST_SESSION)

    assert tmp_store.count_user_messages(TEST_PHONE) == 1


# ── Summarizer Utilities ──────────────────────────────────────────────────

def test_should_summarize_triggers_at_multiples_of_5():
    from src.bhai.memory.summarizer import should_summarize

    assert should_summarize(5) is True
    assert should_summarize(10) is True
    assert should_summarize(15) is True


def test_should_summarize_no_trigger_otherwise():
    from src.bhai.memory.summarizer import should_summarize

    assert should_summarize(0) is False
    assert should_summarize(1) is False
    assert should_summarize(4) is False
    assert should_summarize(6) is False
    assert should_summarize(9) is False


def test_parse_summary_valid_format():
    from src.bhai.memory.summarizer import parse_summary

    raw = (
        "SUMMARY:\n"
        "Yashoda production team mein hai. Pichle mahine bete ki tabiyat kharab thi.\n\n"
        'FACTS:\n["Bete ki tabiyat kharab thi", "Production team mein hai"]'
    )

    result = parse_summary(raw)
    assert "Yashoda" in result["summary"]
    assert len(result["facts"]) == 2
    assert "Bete ki tabiyat kharab thi" in result["facts"]


def test_parse_summary_fallback_on_missing_tags():
    from src.bhai.memory.summarizer import parse_summary

    raw = "This is unparseable raw text from the LLM."
    result = parse_summary(raw)
    # Falls back to raw text as summary rather than crashing
    assert len(result["summary"]) > 0
    assert isinstance(result["facts"], list)


def test_merge_facts_deduplicates():
    from src.bhai.memory.summarizer import merge_facts

    old = ["Bete ki tabiyat kharab thi", "Salary kata tha"]
    new = ["Salary kata tha", "Overtime mil gaya"]

    merged = merge_facts(old, new)
    assert len(merged) == 3
    assert "Salary kata tha" in merged
    assert "Overtime mil gaya" in merged


def test_merge_facts_deduplicates_case_insensitive():
    from src.bhai.memory.summarizer import merge_facts

    old = ["SALARY kata tha"]
    new = ["salary kata tha"]
    merged = merge_facts(old, new)
    assert len(merged) == 1


def test_merge_facts_empty_inputs():
    from src.bhai.memory.summarizer import merge_facts

    assert merge_facts([], []) == []
    assert merge_facts(["one"], []) == ["one"]
    assert merge_facts([], ["two"]) == ["two"]


def test_build_summarize_request_no_old_summary():
    from src.bhai.memory.summarizer import build_summarize_request

    messages = [
        {"role": "user", "content": "Namaste"},
        {"role": "assistant", "content": "Namaste! Kaisa hai?"},
    ]
    prompt = build_summarize_request("", messages)
    assert "pehli baatcheet" in prompt
    assert "Namaste" in prompt


def test_build_summarize_request_with_old_summary():
    from src.bhai.memory.summarizer import build_summarize_request

    old = "Yashoda production mein hai."
    messages = [{"role": "user", "content": "Leave leni hai kal"}]
    prompt = build_summarize_request(old, messages)
    assert old in prompt
    assert "Leave leni hai" in prompt
