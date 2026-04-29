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
    SKIP_IF_USER_ACTIVE_HOURS,
    SLOT_MORNING,
    SLOT_NIGHT,
    NUDGE_INSTRUCTION,
    build_nudge_prompts,
    current_slot,
    parse_allowlist,
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
    assert (
        should_nudge_user(
            now_ist=now,
            slot="afternoon",
            last_user_message_at=None,
            last_nudge_at=None,
        )
        is False
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


# ── build_nudge_prompts ───────────────────────────────────────────────


def _stub_llm():
    """Minimal LLM stub — only `_build_system_prompt` is consulted by build_nudge_prompts."""
    llm = MagicMock()
    llm._build_system_prompt = MagicMock(
        return_value="<<SYSTEM PROMPT BODY>>"
    )
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
    assert "1-2 sentences MAX" in sys_p
    assert "No markdown" in sys_p
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


def test_nudge_instruction_forbids_escalate_emotions():
    """The nudge text must be plain — no ESCALATE/EMOTIONS_JSON post-processing."""
    assert "ESCALATE" in NUDGE_INSTRUCTION
    assert "EMOTIONS_JSON" in NUDGE_INSTRUCTION
    assert "no" in NUDGE_INSTRUCTION.lower()
