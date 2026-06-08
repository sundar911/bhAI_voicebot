"""Tests for the v2 open-threads pipeline.

Piece A: the reactive LLM emits `<thread>` blocks alongside `<memory>`
blocks; ``BaseLLM`` parses them into ``ThreadPatch`` objects and strips
them before the response goes to TTS.

Piece B: ``ConversationStore.apply_thread_patches`` persists those
patches as ``Thread`` rows in an encrypted SQLite table with explicit
state transitions (``dormant``/``active``/``closed``/``do_not_nudge``).
``mark_thread_nudged`` is the hook the proactive thinker (piece D) will
call after firing a nudge that references a thread.
"""

from __future__ import annotations

import pytest

from bhai.llm.base import BaseLLM
from bhai.memory.store import ConversationStore
from bhai.proactive.threads import (
    MAX_HISTORY_ENTRIES,
    SLUG_PATTERN,
    THREAD_OPS,
    THREAD_STATES,
    Thread,
    ThreadPatch,
)


@pytest.fixture
def store(tmp_db):
    """Fresh ConversationStore for each persistence test."""
    s = ConversationStore(tmp_db)
    yield s
    s.close()


# ── ThreadPatch validation ─────────────────────────────────────────────


def test_thread_patch_open_valid():
    p = ThreadPatch(op="open", topic="saree_business_expansion", context="₹1L loan")
    assert p.is_valid()


def test_thread_patch_close_valid():
    p = ThreadPatch(op="close", topic="saree_business_expansion", context="resolved")
    assert p.is_valid()


def test_thread_patch_mark_sensitive_valid_with_empty_context():
    """mark_sensitive is the one op where context is optional — it's a flag."""
    p = ThreadPatch(op="mark_sensitive", topic="daughter_recovery", context="")
    assert p.is_valid()


def test_thread_patch_invalid_op():
    p = ThreadPatch(op="delete", topic="foo", context="bar")
    assert not p.is_valid()


def test_thread_patch_invalid_slug_with_hyphen():
    """Hyphens are intentionally excluded from slugs — see threads.py."""
    p = ThreadPatch(op="open", topic="saree-business", context="x")
    assert not p.is_valid()


def test_thread_patch_invalid_slug_with_space():
    p = ThreadPatch(op="open", topic="saree business", context="x")
    assert not p.is_valid()


def test_thread_patch_invalid_open_missing_context():
    p = ThreadPatch(op="open", topic="saree_business_expansion", context="")
    assert not p.is_valid()


def test_thread_ops_constant_covers_all_documented_ops():
    """Guardrail: if the documented ops in THREAD_INSTRUCTION drift from
    the THREAD_OPS allowlist, the parser will silently start dropping
    new ops as 'unknown' — keep the two in lockstep."""
    assert set(THREAD_OPS) == {"open", "update", "close", "mark_sensitive"}


def test_slug_pattern_accepts_underscores_digits_lowercase():
    assert SLUG_PATTERN.match("saree_business_2026")
    assert not SLUG_PATTERN.match("Saree_Business")  # case-sensitive
    assert not SLUG_PATTERN.match("")  # empty
    assert not SLUG_PATTERN.match("a" * 81)  # too long


# ── _strip_thread_patches ──────────────────────────────────────────────


def test_strip_thread_patches_removes_single_block():
    raw = (
        "मणीमाला जी, समझ गई। बस ₹8000 EMI थोड़ा tight लगेगा। "
        "<thread>open: saree_business_expansion / ₹1L loan plan for Surat supplier diversification</thread>"
    )
    cleaned = BaseLLM._strip_thread_patches(raw)
    assert "<thread>" not in cleaned
    assert "open:" not in cleaned
    assert "₹8000 EMI" in cleaned


def test_strip_thread_patches_removes_multiple_blocks():
    raw = (
        "ठीक है। <thread>open: a / one</thread> "
        "<thread>update: b / two</thread> "
        "<thread>mark_sensitive: c</thread>"
    )
    cleaned = BaseLLM._strip_thread_patches(raw)
    assert "<thread>" not in cleaned
    assert "ठीक है।" in cleaned


def test_strip_thread_patches_idempotent_on_clean_text():
    raw = "नमस्ते, सब ठीक है ना?"
    assert BaseLLM._strip_thread_patches(raw) == raw


def test_strip_thread_patches_case_insensitive_tag():
    raw = "ठीक <THREAD>open: x / hello</THREAD> done."
    cleaned = BaseLLM._strip_thread_patches(raw)
    assert "<thread>" not in cleaned.lower()
    assert "open:" not in cleaned


def test_strip_thread_patches_handles_multiline_context():
    """DOTALL — open/update context can span multiple lines."""
    raw = (
        "ठीक है।\n"
        "<thread>open: x / line one\n"
        "line two\n"
        "line three</thread>\n"
        "और कुछ बात?"
    )
    cleaned = BaseLLM._strip_thread_patches(raw)
    assert "<thread>" not in cleaned
    assert "line one" not in cleaned
    assert "और कुछ बात?" in cleaned


# ── _parse_thread_patches ──────────────────────────────────────────────


def test_parse_thread_patches_open():
    raw = (
        "<thread>open: saree_business_expansion / Manimala mentioned ₹1L loan</thread>"
    )
    patches = BaseLLM._parse_thread_patches(raw)
    assert patches is not None
    assert len(patches) == 1
    p = patches[0]
    assert p.op == "open"
    assert p.topic == "saree_business_expansion"
    assert "Manimala mentioned" in p.context


def test_parse_thread_patches_update():
    raw = (
        "<thread>update: saree_business_expansion / "
        "Decided not to take loan after the EMI math</thread>"
    )
    patches = BaseLLM._parse_thread_patches(raw)
    assert patches is not None
    assert patches[0].op == "update"
    assert "Decided not to take loan" in patches[0].context


def test_parse_thread_patches_close():
    raw = (
        "<thread>close: saree_business_expansion / "
        "User went to Surat and bought 3-month inventory; resolved</thread>"
    )
    patches = BaseLLM._parse_thread_patches(raw)
    assert patches is not None
    assert patches[0].op == "close"


def test_parse_thread_patches_mark_sensitive_no_context():
    raw = "<thread>mark_sensitive: daughter_recovery</thread>"
    patches = BaseLLM._parse_thread_patches(raw)
    assert patches is not None
    assert patches[0].op == "mark_sensitive"
    assert patches[0].topic == "daughter_recovery"
    assert patches[0].context == ""


def test_parse_thread_patches_returns_none_when_absent():
    assert BaseLLM._parse_thread_patches("just a normal reply") is None
    assert BaseLLM._parse_thread_patches("") is None


def test_parse_thread_patches_preserves_emission_order():
    raw = (
        "<thread>open: a / first</thread>"
        "<thread>open: b / second</thread>"
        "<thread>open: c / third</thread>"
    )
    patches = BaseLLM._parse_thread_patches(raw)
    assert patches is not None
    assert [p.topic for p in patches] == ["a", "b", "c"]


def test_parse_thread_patches_drops_unknown_op():
    """Unknown ops (e.g. 'delete') are logged and skipped, not coerced."""
    raw = (
        "<thread>delete: saree_business_expansion / drop me</thread>"
        "<thread>open: real_thread / kept</thread>"
    )
    patches = BaseLLM._parse_thread_patches(raw)
    assert patches is not None
    assert len(patches) == 1
    assert patches[0].topic == "real_thread"


def test_parse_thread_patches_drops_bad_slug():
    """Hyphenated slugs are invalid; the parser drops the patch."""
    raw = "<thread>open: saree-business / bad slug</thread>"
    patches = BaseLLM._parse_thread_patches(raw)
    assert patches is None


def test_parse_thread_patches_drops_missing_separator():
    """open/update/close need ' / ' between slug and context."""
    raw = "<thread>open: missing_slash_separator</thread>"
    patches = BaseLLM._parse_thread_patches(raw)
    assert patches is None


def test_parse_thread_patches_drops_empty_open_context():
    """An open op without context is malformed — drop it."""
    raw = "<thread>open: foo / </thread>"
    patches = BaseLLM._parse_thread_patches(raw)
    assert patches is None


def test_parse_thread_patches_mixed_with_memory_blocks():
    """Threads coexist with memory blocks in the same response — each is
    parsed by its own parser, neither contaminates the other."""
    raw = (
        "अरे ठीक है।"
        "<memory>fact: planning ₹1L loan</memory>"
        "<thread>open: saree_business_expansion / ₹1L loan for Surat</thread>"
        "<memory>fact: work_location: BC</memory>"
    )
    threads = BaseLLM._parse_thread_patches(raw)
    memory = BaseLLM._parse_memory_patches(raw)
    assert threads is not None and len(threads) == 1
    assert memory is not None
    assert "planning ₹1L loan" in memory["facts"]
    assert threads[0].topic == "saree_business_expansion"


# ── clean_response strips thread blocks alongside memory ───────────────


def test_clean_response_strips_thread_blocks_before_tts():
    raw = (
        "अरे, समझ गई।\n"
        "<memory>fact: planning Surat trip</memory>\n"
        "<thread>open: surat_diwali_trip / planning Diwali Surat trip for new inventory</thread>"
    )
    cleaned = BaseLLM._clean_response(raw)
    assert "<thread>" not in cleaned
    assert "<memory>" not in cleaned
    assert "fact:" not in cleaned
    assert "open:" not in cleaned
    assert "समझ गई" in cleaned


# ── Persistence — apply_thread_patches state transitions ───────────────


def test_thread_states_constant_matches_expected():
    """Guardrail: state allowlist drift would silently break
    apply_thread_patches' assertions."""
    assert set(THREAD_STATES) == {"dormant", "active", "closed", "do_not_nudge"}


def test_apply_open_on_new_slug_inserts_dormant_row(store):
    phone = "tg_111"
    patches = [
        ThreadPatch(op="open", topic="saree_business", context="₹1L Surat loan plan")
    ]
    counts = store.apply_thread_patches(phone, patches)
    assert counts == {
        "opened": 1,
        "updated": 0,
        "closed": 0,
        "marked_sensitive": 0,
        "skipped": 0,
    }

    thread = store.get_thread(phone, "saree_business")
    assert thread is not None
    assert thread.state == "dormant"
    assert thread.context == "₹1L Surat loan plan"
    assert thread.last_nudged_at is None
    assert len(thread.history) == 1
    assert thread.history[0]["op"] == "open"
    assert thread.history[0]["context"] == "₹1L Surat loan plan"


def test_apply_open_on_closed_slug_reopens_as_dormant(store):
    phone = "tg_222"
    store.apply_thread_patches(
        phone, [ThreadPatch(op="open", topic="surat_trip", context="planning")]
    )
    store.apply_thread_patches(
        phone, [ThreadPatch(op="close", topic="surat_trip", context="trip done")]
    )
    closed = store.get_thread(phone, "surat_trip")
    assert closed is not None and closed.state == "closed"

    counts = store.apply_thread_patches(
        phone,
        [ThreadPatch(op="open", topic="surat_trip", context="new Surat trip planned")],
    )
    assert counts["opened"] == 1
    reopened = store.get_thread(phone, "surat_trip")
    assert reopened is not None
    assert reopened.state == "dormant"
    assert reopened.context == "new Surat trip planned"
    # History grows — close + reopen both appear
    ops = [h["op"] for h in reopened.history]
    assert ops == ["open", "close", "open"]


def test_apply_open_on_already_active_slug_is_treated_as_update(store):
    """Defensive: the LLM may re-emit `open` for a thread it already
    opened. Persist the new context as an update rather than crashing
    or double-creating."""
    phone = "tg_333"
    store.apply_thread_patches(
        phone, [ThreadPatch(op="open", topic="loan_plan", context="initial plan")]
    )
    counts = store.apply_thread_patches(
        phone,
        [ThreadPatch(op="open", topic="loan_plan", context="refined ₹80k plan")],
    )
    assert counts["opened"] == 0
    assert counts["updated"] == 1
    thread = store.get_thread(phone, "loan_plan")
    assert thread is not None
    assert thread.state == "dormant"
    assert thread.context == "refined ₹80k plan"


def test_apply_update_on_existing_thread_refreshes_context(store):
    phone = "tg_444"
    store.apply_thread_patches(
        phone, [ThreadPatch(op="open", topic="son_classes", context="painting class")]
    )
    counts = store.apply_thread_patches(
        phone,
        [
            ThreadPatch(
                op="update",
                topic="son_classes",
                context="also asked about karate",
            )
        ],
    )
    assert counts["updated"] == 1
    thread = store.get_thread(phone, "son_classes")
    assert thread is not None
    assert thread.context == "also asked about karate"
    # State stays dormant
    assert thread.state == "dormant"
    # History captures both ops in order
    assert [h["op"] for h in thread.history] == ["open", "update"]


def test_apply_update_on_missing_slug_auto_promotes_to_dormant(store):
    phone = "tg_555"
    counts = store.apply_thread_patches(
        phone,
        [ThreadPatch(op="update", topic="orphan", context="appeared without an open")],
    )
    # Auto-promotion is counted under `opened`, not `updated`
    assert counts == {
        "opened": 1,
        "updated": 0,
        "closed": 0,
        "marked_sensitive": 0,
        "skipped": 0,
    }
    thread = store.get_thread(phone, "orphan")
    assert thread is not None
    assert thread.state == "dormant"
    assert thread.context == "appeared without an open"


def test_apply_close_on_existing_thread_marks_closed(store):
    phone = "tg_666"
    store.apply_thread_patches(
        phone, [ThreadPatch(op="open", topic="diwali_trip", context="planning")]
    )
    counts = store.apply_thread_patches(
        phone,
        [ThreadPatch(op="close", topic="diwali_trip", context="trip completed")],
    )
    assert counts["closed"] == 1
    thread = store.get_thread(phone, "diwali_trip")
    assert thread is not None
    assert thread.state == "closed"
    assert thread.context == "trip completed"


def test_apply_close_on_missing_slug_is_skipped(store):
    phone = "tg_777"
    counts = store.apply_thread_patches(
        phone,
        [ThreadPatch(op="close", topic="never_opened", context="nothing to close")],
    )
    assert counts == {
        "opened": 0,
        "updated": 0,
        "closed": 0,
        "marked_sensitive": 0,
        "skipped": 1,
    }
    assert store.get_thread(phone, "never_opened") is None


def test_apply_mark_sensitive_on_existing_thread(store):
    """mark_sensitive preserves the existing context — we still want
    situational awareness in the dossier, just not nudging."""
    phone = "tg_888"
    store.apply_thread_patches(
        phone,
        [
            ThreadPatch(
                op="open",
                topic="daughter_recovery",
                context="surgery recovery in progress",
            )
        ],
    )
    counts = store.apply_thread_patches(
        phone, [ThreadPatch(op="mark_sensitive", topic="daughter_recovery")]
    )
    assert counts["marked_sensitive"] == 1
    thread = store.get_thread(phone, "daughter_recovery")
    assert thread is not None
    assert thread.state == "do_not_nudge"
    # Context is preserved — only the state changes
    assert thread.context == "surgery recovery in progress"


def test_apply_mark_sensitive_on_missing_slug_creates_do_not_nudge_row(store):
    """If the agent decides a topic is sensitive before the LLM has
    formally opened it, we still want a row to block future nudges."""
    phone = "tg_999"
    counts = store.apply_thread_patches(
        phone, [ThreadPatch(op="mark_sensitive", topic="caste_topic")]
    )
    assert counts["marked_sensitive"] == 1
    thread = store.get_thread(phone, "caste_topic")
    assert thread is not None
    assert thread.state == "do_not_nudge"
    assert thread.context == ""


def test_apply_invalid_patches_are_counted_as_skipped(store):
    """Patches failing ThreadPatch.is_valid get logged and skipped,
    never raised — the reactive loop has to be robust to LLM noise."""
    phone = "tg_aaa"
    bad = [
        ThreadPatch(op="delete", topic="x", context="unknown op"),
        ThreadPatch(op="open", topic="BadCase", context="invalid slug"),
        ThreadPatch(op="open", topic="ok_topic", context=""),  # empty context
    ]
    counts = store.apply_thread_patches(phone, bad)
    assert counts["skipped"] == 3
    assert counts["opened"] == 0
    assert store.get_thread(phone, "x") is None
    assert store.get_thread(phone, "ok_topic") is None


def test_apply_batch_with_mixed_ops_returns_accurate_counts(store):
    """A realistic batch: open new, update existing, close one,
    mark another sensitive — all in one turn."""
    phone = "tg_bbb"
    # Seed two threads first
    store.apply_thread_patches(
        phone,
        [
            ThreadPatch(op="open", topic="loan_plan", context="₹1L"),
            ThreadPatch(op="open", topic="son_class", context="karate"),
        ],
    )
    counts = store.apply_thread_patches(
        phone,
        [
            ThreadPatch(op="open", topic="new_topic", context="just surfaced"),
            ThreadPatch(op="update", topic="loan_plan", context="reduced to ₹50k"),
            ThreadPatch(op="close", topic="son_class", context="enrolled"),
            ThreadPatch(op="mark_sensitive", topic="health_topic"),
        ],
    )
    assert counts == {
        "opened": 1,
        "updated": 1,
        "closed": 1,
        "marked_sensitive": 1,
        "skipped": 0,
    }


# ── list_threads / get_thread / mark_thread_nudged ─────────────────────


def test_list_threads_empty_for_unknown_user(store):
    assert store.list_threads("tg_nobody") == []


def test_list_threads_returns_all_states_by_default(store):
    phone = "tg_list"
    store.apply_thread_patches(
        phone,
        [
            ThreadPatch(op="open", topic="a", context="aaa"),
            ThreadPatch(op="open", topic="b", context="bbb"),
            ThreadPatch(op="open", topic="c", context="ccc"),
        ],
    )
    store.apply_thread_patches(
        phone, [ThreadPatch(op="close", topic="c", context="done")]
    )

    threads = store.list_threads(phone)
    assert len(threads) == 3
    slugs = {t.slug for t in threads}
    assert slugs == {"a", "b", "c"}
    # `c` was the most recently touched (the close op) so it leads
    assert threads[0].slug == "c"


def test_list_threads_filters_by_states(store):
    phone = "tg_filter"
    store.apply_thread_patches(
        phone,
        [
            ThreadPatch(op="open", topic="a", context="x"),
            ThreadPatch(op="open", topic="b", context="x"),
            ThreadPatch(op="open", topic="c", context="x"),
        ],
    )
    store.apply_thread_patches(
        phone,
        [
            ThreadPatch(op="close", topic="b", context="done"),
            ThreadPatch(op="mark_sensitive", topic="c"),
        ],
    )

    dormant_only = store.list_threads(phone, states=["dormant"])
    assert {t.slug for t in dormant_only} == {"a"}

    closed_or_sensitive = store.list_threads(phone, states=["closed", "do_not_nudge"])
    assert {t.slug for t in closed_or_sensitive} == {"b", "c"}


def test_get_thread_returns_thread_dataclass(store):
    phone = "tg_get"
    store.apply_thread_patches(
        phone, [ThreadPatch(op="open", topic="x", context="ctx")]
    )
    thread = store.get_thread(phone, "x")
    assert isinstance(thread, Thread)
    assert thread.phone == phone
    assert thread.slug == "x"
    assert thread.state == "dormant"
    assert thread.opened_at  # ISO timestamp populated
    assert thread.last_touched_at  # ISO timestamp populated


def test_mark_thread_nudged_transitions_dormant_to_active(store):
    phone = "tg_nudge1"
    store.apply_thread_patches(
        phone, [ThreadPatch(op="open", topic="topic", context="ctx")]
    )
    assert store.mark_thread_nudged(phone, "topic") is True

    thread = store.get_thread(phone, "topic")
    assert thread is not None
    assert thread.state == "active"
    assert thread.last_nudged_at is not None


def test_mark_thread_nudged_on_active_keeps_state_refreshes_timestamp(store):
    """Already-active threads stay active but get their last_nudged_at
    refreshed so the thinker has an accurate 'I poked it again' signal."""
    phone = "tg_nudge2"
    store.apply_thread_patches(
        phone, [ThreadPatch(op="open", topic="topic", context="ctx")]
    )
    store.mark_thread_nudged(phone, "topic")
    first_nudge = store.get_thread(phone, "topic").last_nudged_at

    # Sleep is unnecessary — ISO precision is fine — but the second
    # call should at least preserve activeness and overwrite the
    # timestamp without error.
    store.mark_thread_nudged(phone, "topic")
    second = store.get_thread(phone, "topic")
    assert second.state == "active"
    assert second.last_nudged_at is not None
    assert second.last_nudged_at >= first_nudge


def test_mark_thread_nudged_on_closed_keeps_closed_but_records_timestamp(store):
    """The thinker shouldn't normally nudge closed threads, but if it
    does we record the timestamp without un-closing the thread."""
    phone = "tg_nudge3"
    store.apply_thread_patches(
        phone, [ThreadPatch(op="open", topic="t", context="ctx")]
    )
    store.apply_thread_patches(
        phone, [ThreadPatch(op="close", topic="t", context="done")]
    )

    assert store.mark_thread_nudged(phone, "t") is True
    thread = store.get_thread(phone, "t")
    assert thread.state == "closed"
    assert thread.last_nudged_at is not None


def test_mark_thread_nudged_on_do_not_nudge_keeps_state(store):
    """mark_sensitive threads stay do_not_nudge regardless of any
    accidental thinker call — sticky safety."""
    phone = "tg_nudge4"
    store.apply_thread_patches(
        phone, [ThreadPatch(op="mark_sensitive", topic="sensitive")]
    )
    store.mark_thread_nudged(phone, "sensitive")
    thread = store.get_thread(phone, "sensitive")
    assert thread.state == "do_not_nudge"


def test_mark_thread_nudged_missing_slug_returns_false(store):
    assert store.mark_thread_nudged("tg_x", "missing") is False


# ── Encryption at rest ─────────────────────────────────────────────────


def test_thread_context_is_encrypted_at_rest(store, tmp_db):
    """Raw SQLite bytes must not contain plaintext thread context.
    Thread context routinely contains business plans, family details,
    and other sensitive material — same threat model as memory."""
    phone = "tg_crypt"
    store.apply_thread_patches(
        phone,
        [
            ThreadPatch(
                op="open",
                topic="loan_plan",
                context="secret-loan-amount-marker-₹4567",
            )
        ],
    )
    store.close()

    raw = tmp_db.read_bytes()
    assert b"secret-loan-amount-marker" not in raw


# ── History capping ────────────────────────────────────────────────────


def test_history_capped_at_max_entries(store):
    """Pathological case: a chatty thread updated 30 times shouldn't
    grow the encrypted history blob unboundedly. Oldest entries fall
    off first."""
    phone = "tg_hist"
    store.apply_thread_patches(
        phone, [ThreadPatch(op="open", topic="t", context="initial")]
    )
    # +30 updates → 31 total entries; should trim to MAX_HISTORY_ENTRIES.
    for i in range(30):
        store.apply_thread_patches(
            phone,
            [ThreadPatch(op="update", topic="t", context=f"update {i}")],
        )

    thread = store.get_thread(phone, "t")
    assert thread is not None
    assert len(thread.history) == MAX_HISTORY_ENTRIES
    # Newest entry is preserved; oldest (`initial`) is dropped
    assert thread.history[-1]["context"] == "update 29"
    assert all(h["context"] != "initial" for h in thread.history)


# ── merge_user / delete_user cover threads ─────────────────────────────


def test_delete_user_wipes_threads(store):
    """delete_user must clear the threads table for the phone alongside
    messages/memory/nudges."""
    phone = "tg_wipe"
    other = "tg_keep"
    store.apply_thread_patches(
        phone, [ThreadPatch(op="open", topic="x", context="ctx")]
    )
    store.apply_thread_patches(
        other, [ThreadPatch(op="open", topic="y", context="keep me")]
    )

    counts = store.delete_user(phone)
    assert counts["threads_deleted"] == 1
    assert store.get_thread(phone, "x") is None

    # Other user's thread is untouched
    assert store.get_thread(other, "y") is not None


def test_merge_user_moves_threads_to_target_phone(store):
    """merge_user (Twilio→Telegram migration) must carry threads over."""
    twilio = "+919000000000"
    telegram = "tg_merge"
    store.apply_thread_patches(
        twilio,
        [
            ThreadPatch(op="open", topic="loan_plan", context="₹1L"),
            ThreadPatch(op="open", topic="son_class", context="karate"),
        ],
    )

    counts = store.merge_user(from_phone=twilio, to_phone=telegram)
    assert counts["threads_migrated"] == 2

    assert store.list_threads(twilio) == []
    assert {t.slug for t in store.list_threads(telegram)} == {
        "loan_plan",
        "son_class",
    }


def test_merge_user_overwrites_target_threads_on_conflict(store):
    """If the target phone has stale threads pre-merge, they get cleared
    so the source's threads land cleanly — same pattern as memory/nudges."""
    twilio = "+919111111111"
    telegram = "tg_overwrite"

    # Source: real thread we want to migrate
    store.apply_thread_patches(
        twilio, [ThreadPatch(op="open", topic="real_thread", context="from twilio")]
    )
    # Target: stale thread that must be dropped
    store.apply_thread_patches(
        telegram,
        [ThreadPatch(op="open", topic="stale_thread", context="leftover")],
    )

    store.merge_user(from_phone=twilio, to_phone=telegram)

    slugs = {t.slug for t in store.list_threads(telegram)}
    assert slugs == {"real_thread"}
    assert "stale_thread" not in slugs


# ── record_nudge_outcome (piece D delivery hook) ───────────────────────


class TestRecordNudgeOutcome:
    """The atomic post-delivery hook the schedulers call after a
    successful send. Wraps record_nudge_sent + mark_thread_nudged so
    callers don't have to remember to do both."""

    def test_outcome_with_thread_slug_transitions_dormant_to_active(self, store):
        phone = "tg_outcome1"
        store.apply_thread_patches(
            phone, [ThreadPatch(op="open", topic="biz_plan", context="ctx")]
        )
        store.record_nudge_outcome(phone, "morning", thread_slug="biz_plan")

        # Per-slot timestamp was bumped (existing v1.5 throttle gate)
        assert store.get_last_nudge_sent(phone, "morning") is not None
        # Thread transitioned dormant→active
        thread = store.get_thread(phone, "biz_plan")
        assert thread.state == "active"
        assert thread.last_nudged_at is not None

    def test_outcome_with_no_thread_slug_only_records_send(self, store):
        """v1.5 path doesn't pick a thread — outcome should still bump
        the per-slot timestamp without touching any thread row."""
        phone = "tg_outcome2"
        store.apply_thread_patches(
            phone, [ThreadPatch(op="open", topic="biz_plan", context="ctx")]
        )

        store.record_nudge_outcome(phone, "morning", thread_slug=None)
        assert store.get_last_nudge_sent(phone, "morning") is not None
        # Thread is untouched — still dormant, no nudge timestamp.
        thread = store.get_thread(phone, "biz_plan")
        assert thread.state == "dormant"
        assert thread.last_nudged_at is None

    def test_outcome_with_unknown_slug_still_records_send(self, store):
        """Defensive: if the thinker emits a slug that doesn't exist in
        the store (e.g. brand-new thread the LLM hallucinated), the
        per-slot timestamp still bumps — we don't lose throttle gating
        because of a bad slug."""
        phone = "tg_outcome3"
        store.record_nudge_outcome(phone, "morning", thread_slug="nonexistent")
        assert store.get_last_nudge_sent(phone, "morning") is not None
