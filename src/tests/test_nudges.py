"""
Tests for inference/webhooks/nudges.py — pure decision logic + prompt builder.

We do not exercise the asyncio loop or real LLM/TTS calls — those are
integration concerns. Here we lock down the behaviour that decides WHO
gets nudged, WHEN, and WHAT system prompt the LLM receives.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from inference.webhooks.nudges import (
    MIN_GAP_BETWEEN_SAME_SLOT_HOURS,
    NUDGE_INSTRUCTION,
    SKIP_IF_USER_ACTIVE_HOURS,
    SLOT_MORNING,
    SLOT_NIGHT,
    build_nudge_prompts,
    current_slot,
    generate_nudge_text,
    is_wildcard_allowlist,
    parse_allowlist,
    select_nudge_candidates,
    should_nudge_user,
)

IST = timezone(timedelta(hours=5, minutes=30))


def _ist(year=2026, month=4, day=29, hour=10, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=IST)


# ── current_slot ──────────────────────────────────────────────────────


def test_current_slot_morning_at_window_start():
    assert current_slot(_ist(hour=10, minute=0), 10, 21, 30) == SLOT_MORNING


def test_current_slot_morning_inside_window():
    assert current_slot(_ist(hour=10, minute=15), 10, 21, 30) == SLOT_MORNING


def test_current_slot_morning_at_window_edge():
    assert current_slot(_ist(hour=10, minute=30), 10, 21, 30) == SLOT_MORNING


def test_current_slot_morning_outside_window():
    assert current_slot(_ist(hour=10, minute=31), 10, 21, 30) is None


def test_current_slot_night_inside_window():
    assert current_slot(_ist(hour=21, minute=10), 10, 21, 30) == SLOT_NIGHT


def test_current_slot_quiet_hours_pre_morning():
    """Hard guard — never fire before 8am even if a slot is configured."""
    assert current_slot(_ist(hour=7, minute=0), 7, 21, 30) is None


def test_current_slot_quiet_hours_post_night():
    """Hard guard — never fire at/after 23:00 even if a slot is configured."""
    assert current_slot(_ist(hour=23, minute=0), 10, 23, 30) is None


def test_current_slot_between_windows_returns_none():
    assert current_slot(_ist(hour=15, minute=0), 10, 21, 30) is None


# ── should_nudge_user ─────────────────────────────────────────────────


def test_should_nudge_fresh_user_yes():
    """No prior message, no prior nudge → fire it."""
    now = _ist(hour=10)
    assert (
        should_nudge_user(
            now_ist=now,
            slot=SLOT_MORNING,
            last_user_message_at=None,
            last_nudge_at=None,
        )
        is True
    )


def test_should_nudge_skip_if_user_just_messaged():
    """User just messaged us — don't interrupt."""
    now = _ist(hour=10)
    assert (
        should_nudge_user(
            now_ist=now,
            slot=SLOT_MORNING,
            last_user_message_at=now - timedelta(minutes=30),
            last_nudge_at=None,
        )
        is False
    )


def test_should_nudge_ok_if_user_inactive_for_active_threshold():
    """Past the active-conversation window → ok to nudge."""
    now = _ist(hour=10)
    assert (
        should_nudge_user(
            now_ist=now,
            slot=SLOT_MORNING,
            last_user_message_at=now - timedelta(hours=SKIP_IF_USER_ACTIVE_HOURS + 1),
            last_nudge_at=None,
        )
        is True
    )


def test_should_nudge_skip_if_same_slot_just_fired():
    """Same slot fired recently — don't double-fire (handles loop overlap)."""
    now = _ist(hour=10)
    assert (
        should_nudge_user(
            now_ist=now,
            slot=SLOT_MORNING,
            last_user_message_at=None,
            last_nudge_at=now - timedelta(hours=2),
        )
        is False
    )


def test_should_nudge_ok_if_same_slot_was_yesterday():
    now = _ist(hour=10)
    assert (
        should_nudge_user(
            now_ist=now,
            slot=SLOT_MORNING,
            last_user_message_at=None,
            last_nudge_at=now - timedelta(hours=MIN_GAP_BETWEEN_SAME_SLOT_HOURS + 1),
        )
        is True
    )


def test_should_nudge_rejects_unknown_slot():
    now = _ist(hour=10)
    # "afternoon" is now a real slot (the joke slot); a genuinely unknown one isn't.
    assert (
        should_nudge_user(
            now_ist=now,
            slot="midnight",
            last_user_message_at=None,
            last_nudge_at=None,
        )
        is False
    )
    assert should_nudge_user(
        now_ist=now,
        slot="afternoon",
        last_user_message_at=None,
        last_nudge_at=None,
    )


# ── per-user throttle override ────────────────────────────────────────


def test_should_nudge_throttle_skips_within_window():
    """When throttle is set, ANY-slot nudge inside the window blocks new nudge."""
    now = _ist(hour=10)
    # User asked for once-every-2-days; night nudge fired 12h ago.
    assert (
        should_nudge_user(
            now_ist=now,
            slot=SLOT_MORNING,
            last_user_message_at=None,
            last_nudge_at=None,  # no prior morning nudge
            throttle_hours=48,
            last_any_nudge_at=now - timedelta(hours=12),
        )
        is False
    )


def test_should_nudge_throttle_allows_outside_window():
    """When throttle is set and last nudge was outside window, fire."""
    now = _ist(hour=10)
    assert (
        should_nudge_user(
            now_ist=now,
            slot=SLOT_MORNING,
            last_user_message_at=None,
            last_nudge_at=None,
            throttle_hours=48,
            last_any_nudge_at=now - timedelta(hours=49),
        )
        is True
    )


def test_should_nudge_throttle_overrides_default_slot_gap():
    """Throttle replaces the per-slot gap — so a same-slot 2h-old nudge that
    would normally block is irrelevant when throttle uses any-slot timing."""
    now = _ist(hour=10)
    # Same-slot fired 2h ago (would normally block at 18h),
    # but the user has a 48h throttle and any-slot last was 49h ago → fire.
    assert (
        should_nudge_user(
            now_ist=now,
            slot=SLOT_MORNING,
            last_user_message_at=None,
            last_nudge_at=now - timedelta(hours=2),
            throttle_hours=48,
            last_any_nudge_at=now - timedelta(hours=49),
        )
        is True
    )


def test_should_nudge_no_throttle_uses_default_gap():
    """Absent throttle, falls back to MIN_GAP_BETWEEN_SAME_SLOT_HOURS check."""
    now = _ist(hour=10)
    assert (
        should_nudge_user(
            now_ist=now,
            slot=SLOT_MORNING,
            last_user_message_at=None,
            last_nudge_at=now - timedelta(hours=2),
            throttle_hours=None,
            last_any_nudge_at=None,
        )
        is False
    )


def test_should_nudge_throttle_zero_treated_as_no_throttle():
    """throttle_hours=0 is a no-op (cleared); falls back to default logic."""
    now = _ist(hour=10)
    assert (
        should_nudge_user(
            now_ist=now,
            slot=SLOT_MORNING,
            last_user_message_at=None,
            last_nudge_at=now - timedelta(hours=MIN_GAP_BETWEEN_SAME_SLOT_HOURS + 1),
            throttle_hours=0,
            last_any_nudge_at=now - timedelta(hours=1),
        )
        is True
    )


# ── parse_allowlist ───────────────────────────────────────────────────


def test_parse_allowlist_empty():
    assert parse_allowlist("") == []


def test_parse_allowlist_single():
    assert parse_allowlist("871473eb2147") == ["871473eb2147"]


def test_parse_allowlist_comma_separated():
    assert parse_allowlist("aaa,bbb,ccc") == ["aaa", "bbb", "ccc"]


def test_parse_allowlist_strips_whitespace_and_newlines():
    assert parse_allowlist(" aaa , bbb \n ccc ") == ["aaa", "bbb", "ccc"]


def test_parse_allowlist_drops_empties():
    assert parse_allowlist("aaa,,bbb,") == ["aaa", "bbb"]


# ── Wildcard + candidate selection ────────────────────────────────────


def _identity_hash(phone: str) -> str:
    """Stub `phone_hash_fn` for tests — returns the phone string itself
    so allowlist comparisons are easy to read."""
    return phone


def test_is_wildcard_allowlist_recognises_star():
    assert is_wildcard_allowlist("*") is True
    assert is_wildcard_allowlist(" * ") is True


def test_is_wildcard_allowlist_rejects_other_inputs():
    assert is_wildcard_allowlist("") is False
    assert is_wildcard_allowlist("aaa,bbb") is False
    assert is_wildcard_allowlist("**") is False  # not the sentinel


def test_select_nudge_candidates_wildcard_returns_all_active():
    """With NUDGE_PHONES=*, every active user becomes a candidate."""
    active = ["tg_111", "tg_222", "tg_333"]
    assert select_nudge_candidates(active, "*", _identity_hash) == active


def test_select_nudge_candidates_wildcard_with_no_active_returns_empty():
    """Wildcard doesn't conjure candidates from nothing — still gated by
    `list_recently_active_phones`."""
    assert select_nudge_candidates([], "*", _identity_hash) == []


def test_select_nudge_candidates_explicit_list_filters_correctly():
    active = ["tg_111", "tg_222", "tg_333"]
    result = select_nudge_candidates(active, "tg_111,tg_333", _identity_hash)
    assert result == ["tg_111", "tg_333"]


def test_select_nudge_candidates_empty_allowlist_returns_empty():
    """Defensive default — blank NUDGE_PHONES = nobody nudged."""
    active = ["tg_111", "tg_222"]
    assert select_nudge_candidates(active, "", _identity_hash) == []


def test_select_nudge_candidates_unknown_hash_in_allowlist_is_noop():
    """Stale hashes in the allowlist that don't match any active user are
    silently skipped (no error)."""
    active = ["tg_111"]
    result = select_nudge_candidates(active, "tg_111,tg_DOES_NOT_EXIST", _identity_hash)
    assert result == ["tg_111"]


# ── build_nudge_prompts ───────────────────────────────────────────────


def _stub_llm():
    """Minimal LLM stub — only `_build_system_prompt` is consulted by build_nudge_prompts."""
    llm = MagicMock()
    llm._build_system_prompt = MagicMock(return_value="<<SYSTEM PROMPT BODY>>")
    return llm


def test_build_nudge_prompts_includes_nudge_instruction():
    llm = _stub_llm()
    sys_p, user_p = build_nudge_prompts(
        llm,
        domain="hr_admin",
        slot=SLOT_MORNING,
        user_profile="Yashoda, works at Andheri",
        memory_summary="Talked about her son's school",
        extracted_facts="- son's name is Aarav",
        recent_messages=[
            {"role": "user", "content": "बेटा बीमार था"},
            {"role": "assistant", "content": "अरे, अब कैसा है?"},
        ],
    )
    assert "<<SYSTEM PROMPT BODY>>" in sys_p
    assert "=== Nudge Mode ===" in sys_p
    # v1.5 backport markers — respectful aap-form + warmth-first + anti-relentless.
    assert "AAP-FORM ONLY" in sys_p
    assert "WARMTH FIRST" in sys_p
    assert "NO EMOJIS" in sys_p
    assert "Recently Sent Nudges" in sys_p
    llm._build_system_prompt.assert_called_once_with(
        "hr_admin",
        "Yashoda, works at Andheri",
        "Talked about her son's school",
        "- son's name is Aarav",
    )


def test_build_nudge_prompts_user_message_contains_history():
    llm = _stub_llm()
    _, user_p = build_nudge_prompts(
        llm,
        domain="hr_admin",
        slot=SLOT_NIGHT,
        user_profile="",
        memory_summary="",
        extracted_facts="",
        recent_messages=[
            {"role": "user", "content": "नमस्ते"},
            {"role": "assistant", "content": "नमस्ते भाई"},
        ],
    )
    assert "नमस्ते" in user_p
    assert "Recent Conversation" in user_p
    assert "Time slot:" in user_p
    assert "रात" in user_p  # night-time hint


def test_build_nudge_prompts_handles_no_history():
    """When there's nothing to reference, the LLM is told to keep it casual."""
    llm = _stub_llm()
    _, user_p = build_nudge_prompts(
        llm,
        domain="hr_admin",
        slot=SLOT_MORNING,
        user_profile="",
        memory_summary="",
        extracted_facts="",
        recent_messages=[],
    )
    assert "No prior conversation" in user_p
    assert "Recent Conversation" not in user_p


def test_nudge_instruction_uses_cot_out_contract():
    """The legacy plain-text directives were removed — nudges go through the
    cot/out JSON contract now, so the prompt should NOT instruct the model
    to emit only plain text (that would confuse it into leaking JSON)."""
    assert "Output ONLY the nudge text" not in NUDGE_INSTRUCTION
    assert "EMOTIONS_JSON" not in NUDGE_INSTRUCTION


def test_build_nudge_prompts_injects_recent_nudge_texts():
    """When recent_nudge_texts is provided, the user message includes a
    'Recently Sent Nudges' anti-relentless block that lists each one."""
    llm = _stub_llm()
    _, user_p = build_nudge_prompts(
        llm,
        domain="hr_admin",
        slot=SLOT_MORNING,
        user_profile="",
        memory_summary="",
        extracted_facts="",
        recent_messages=[],
        recent_nudge_texts=[
            "Manimala ji, namaste! Aaj kaise hain?",
            "Manimala ji, shaam ho gayi — aaj ka din kaisa raha?",
        ],
    )
    assert "Recently Sent Nudges" in user_p
    assert "do NOT repeat" in user_p
    assert "Manimala ji, namaste! Aaj kaise hain?" in user_p
    assert "shaam ho gayi" in user_p


def test_build_nudge_prompts_omits_history_block_when_empty():
    """No recent_nudge_texts → no 'Recently Sent Nudges' section."""
    llm = _stub_llm()
    _, user_p = build_nudge_prompts(
        llm,
        domain="hr_admin",
        slot=SLOT_MORNING,
        user_profile="",
        memory_summary="",
        extracted_facts="",
        recent_messages=[],
        recent_nudge_texts=[],
    )
    assert "Recently Sent Nudges" not in user_p

    # Same when None is passed (back-compat with callers that don't supply it).
    _, user_p_none = build_nudge_prompts(
        llm,
        domain="hr_admin",
        slot=SLOT_MORNING,
        user_profile="",
        memory_summary="",
        extracted_facts="",
        recent_messages=[],
    )
    assert "Recently Sent Nudges" not in user_p_none


def test_generate_nudge_text_returns_out_not_cot():
    """generate_nudge_text delivers the parsed 'out' and never the cot."""
    llm = _stub_llm()
    llm._generate_structured = MagicMock(
        return_value={
            "text": "अरे, बेटी की तबियत अब कैसी है?",
            "cot": "returning user — reference daughter's health",
            "raw": '{"cot": "...", "out": "..."}',
            "parsed": True,
        }
    )
    text = generate_nudge_text(
        llm,
        slot=SLOT_MORNING,
        user_profile="",
        memory_summary="",
        extracted_facts="",
        recent_messages=[],
    )
    assert text == "अरे, बेटी की तबियत अब कैसी है?"
    assert "returning user" not in text
    llm._generate_structured.assert_called_once()


def test_generate_nudge_text_skips_on_parse_failure():
    """When cot/out can't be parsed, the nudge is skipped (None) — never the
    canned fallback as an unprompted message."""
    llm = _stub_llm()
    llm._generate_structured = MagicMock(
        return_value={
            "text": "अरे, ज़रा सी गड़बड़ हो गई — एक बार फिर से बोलोगे?",
            "cot": "",
            "raw": "garbage",
            "parsed": False,
        }
    )
    text = generate_nudge_text(
        llm,
        slot=SLOT_MORNING,
        user_profile="",
        memory_summary="",
        extracted_facts="",
        recent_messages=[],
    )
    assert text is None
