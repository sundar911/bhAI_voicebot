"""
Tests for src/bhai/llm/base.py — pure helper methods on BaseLLM.

We test via a minimal stub subclass so we can instantiate BaseLLM
without a real API key or network call.
"""

import pytest

from bhai.config import load_config
from bhai.llm.base import BaseLLM


class StubLLM(BaseLLM):
    """Concrete subclass of BaseLLM that returns a fixed response."""

    model_name = "stub-model"

    def _call_api(self, system_prompt: str, user_message: str) -> str:
        return "सब ठीक है।\nESCALATE: false"


@pytest.fixture
def stub_llm(tmp_knowledge_base):
    cfg = load_config()
    return StubLLM(cfg, knowledge_base_dir=tmp_knowledge_base)


# ── _build_user_message ────────────────────────────────────────────────


def test_build_user_message_simple():
    """With no history, message contains the transcript."""
    msg = BaseLLM._build_user_message("salary kab aayegi?")
    assert "salary kab aayegi?" in msg


def test_build_user_message_with_history():
    """Conversation history appears above the transcript."""
    history = [
        {"role": "user", "content": "PF ke baare mein baat karo"},
        {"role": "assistant", "content": "PF ke liye HR se form lo"},
    ]
    msg = BaseLLM._build_user_message("salary?", conversation_history=history)
    assert "User: PF ke baare mein baat karo" in msg
    assert "bhAI: PF ke liye HR se form lo" in msg
    assert "salary?" in msg


def test_build_user_message_new_session_flag():
    """is_new_session=True adds a new-session notice."""
    msg = BaseLLM._build_user_message("hello", is_new_session=True)
    assert "Nayi conversation" in msg or "nayi" in msg.lower()


# ── _detect_escalation ────────────────────────────────────────────────


def test_detect_escalation_true():
    assert BaseLLM._detect_escalation("Kuch nahi pata.\nESCALATE: true") is True


def test_detect_escalation_false():
    assert (
        BaseLLM._detect_escalation("Salary 5th ko aati hai.\nESCALATE: false") is False
    )


def test_detect_escalation_case_insensitive():
    assert BaseLLM._detect_escalation("Escalate: TRUE") is True


def test_detect_escalation_fallback_on_bare_word():
    """If 'escalate' appears without the colon pattern, still returns True."""
    assert BaseLLM._detect_escalation("please escalate this immediately") is True


def test_detect_escalation_absent_returns_false():
    assert BaseLLM._detect_escalation("Salary 5th ko aati hai.") is False


# ── _clean_response ───────────────────────────────────────────────────


def test_clean_response_removes_escalate_line():
    raw = "Salary 5th ko aati hai.\nESCALATE: false"
    cleaned = BaseLLM._clean_response(raw)
    assert "ESCALATE" not in cleaned
    assert "Salary 5th ko aati hai." in cleaned


def test_clean_response_strips_emotions_when_flag_set():
    raw = (
        "Sab theek hai.\n"
        "ESCALATE: false\n"
        'EMOTIONS_JSON: [{"text": "Sab theek hai.", "emotion": "neutral"}]'
    )
    cleaned = BaseLLM._clean_response(raw, strip_emotions=True)
    assert "EMOTIONS_JSON" not in cleaned
    assert "ESCALATE" not in cleaned
    assert "Sab theek hai." in cleaned


def test_clean_response_keeps_emotions_by_default():
    raw = "Answer.\nESCALATE: false\nEMOTIONS_JSON: []"
    cleaned = BaseLLM._clean_response(raw, strip_emotions=False)
    assert "EMOTIONS_JSON" in cleaned


# ── _parse_emotion_segments ───────────────────────────────────────────


def test_parse_emotion_segments_valid():
    raw = (
        "Salary 5th ko aayegi.\n"
        'EMOTIONS_JSON: [{"text": "Salary 5th ko aayegi.", "emotion": "neutral"}]'
    )
    segments = BaseLLM._parse_emotion_segments(raw)
    assert segments is not None
    assert len(segments) == 1
    assert segments[0]["text"] == "Salary 5th ko aayegi."
    assert segments[0]["emotion"] == "neutral"


def test_parse_emotion_segments_no_json_line():
    assert BaseLLM._parse_emotion_segments("Just a normal response.") is None


def test_parse_emotion_segments_invalid_json():
    raw = "Answer.\nEMOTIONS_JSON: not valid json {"
    assert BaseLLM._parse_emotion_segments(raw) is None


def test_parse_emotion_segments_missing_text_key():
    """Segments without 'text' key are rejected."""
    raw = 'EMOTIONS_JSON: [{"emotion": "neutral"}]'
    assert BaseLLM._parse_emotion_segments(raw) is None


# ── _build_system_prompt ──────────────────────────────────────────────


def test_system_prompt_contains_domain_name(stub_llm):
    prompt = stub_llm._build_system_prompt("hr_admin")
    assert "HR_ADMIN" in prompt.upper() or "hr_admin" in prompt


def test_system_prompt_includes_user_profile(stub_llm):
    prompt = stub_llm._build_system_prompt(
        "hr_admin", user_profile="Yashoda, works night shift."
    )
    assert "Yashoda" in prompt


def test_system_prompt_includes_memory_summary(stub_llm):
    prompt = stub_llm._build_system_prompt(
        "hr_admin", memory_summary="User asked about PF twice."
    )
    assert "PF" in prompt
