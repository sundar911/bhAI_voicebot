"""
Tests for BaseLLM static methods and prompt construction.

Zero API calls — all tests use pure Python logic only.
"""

import pytest
from pathlib import Path


def _make_llm(kb_dir: Path):
    """Instantiate a minimal concrete BaseLLM subclass for testing."""
    from src.bhai.llm.base import BaseLLM
    from src.bhai.config import Config

    class FakeLLM(BaseLLM):
        @property
        def model_name(self) -> str:
            return "fake-model"

        def _call_api(self, system_prompt: str, user_message: str) -> str:
            return "Test Hindi response.\nESCALATE: false"

    return FakeLLM(Config(), knowledge_base_dir=kb_dir)


# ── Escalation Detection ──────────────────────────────────────────────────

def test_detect_escalation_true():
    from src.bhai.llm.base import BaseLLM

    assert BaseLLM._detect_escalation("Some text\nESCALATE: true") is True


def test_detect_escalation_false():
    from src.bhai.llm.base import BaseLLM

    assert BaseLLM._detect_escalation("Some text\nESCALATE: false") is False


def test_detect_escalation_missing_line():
    from src.bhai.llm.base import BaseLLM

    assert BaseLLM._detect_escalation("No escalation marker in this text") is False


def test_detect_escalation_case_insensitive():
    from src.bhai.llm.base import BaseLLM

    assert BaseLLM._detect_escalation("Text\nescalate: TRUE") is True


# ── Response Cleaning ─────────────────────────────────────────────────────

def test_clean_response_strips_escalate_line():
    from src.bhai.llm.base import BaseLLM

    raw = "यह एक अच्छी प्रतिक्रिया है।\nESCALATE: false"
    cleaned = BaseLLM._clean_response(raw)
    assert "ESCALATE" not in cleaned
    assert "यह एक अच्छी" in cleaned


def test_clean_response_strips_emotions_when_flagged():
    from src.bhai.llm.base import BaseLLM

    raw = 'Good response.\nESCALATE: false\nEMOTIONS_JSON: [{"text":"Good","emotion":"neutral"}]'
    cleaned = BaseLLM._clean_response(raw, strip_emotions=True)
    assert "EMOTIONS_JSON" not in cleaned
    assert "Good response" in cleaned


def test_clean_response_keeps_emotions_by_default():
    from src.bhai.llm.base import BaseLLM

    raw = 'Good response.\nEMOTIONS_JSON: [{"text":"Good","emotion":"neutral"}]'
    cleaned = BaseLLM._clean_response(raw, strip_emotions=False)
    assert "EMOTIONS_JSON" in cleaned


# ── Emotion Segment Parsing ───────────────────────────────────────────────

def test_parse_emotion_segments_valid():
    from src.bhai.llm.base import BaseLLM

    raw = 'Response.\nESCALATE: false\nEMOTIONS_JSON: [{"text": "Response.", "emotion": "neutral"}]'
    segments = BaseLLM._parse_emotion_segments(raw)
    assert segments is not None
    assert len(segments) == 1
    assert segments[0]["text"] == "Response."
    assert segments[0]["emotion"] == "neutral"


def test_parse_emotion_segments_multiple():
    from src.bhai.llm.base import BaseLLM

    raw = 'Text.\nEMOTIONS_JSON: [{"text":"Hi","emotion":"excited"},{"text":"bye","emotion":"sad"}]'
    segments = BaseLLM._parse_emotion_segments(raw)
    assert segments is not None
    assert len(segments) == 2


def test_parse_emotion_segments_invalid_json_returns_none():
    from src.bhai.llm.base import BaseLLM

    assert BaseLLM._parse_emotion_segments("Response.\nEMOTIONS_JSON: not_json") is None


def test_parse_emotion_segments_missing_returns_none():
    from src.bhai.llm.base import BaseLLM

    assert BaseLLM._parse_emotion_segments("Response with no emotions line.") is None


# ── User Message Building ─────────────────────────────────────────────────

def test_build_user_message_no_history():
    from src.bhai.llm.base import BaseLLM

    msg = BaseLLM._build_user_message("Namaste bhai", conversation_history=None)
    assert "Namaste bhai" in msg
    # No history block should be present
    assert "=== Recent Conversation ===" not in msg


def test_build_user_message_with_history():
    from src.bhai.llm.base import BaseLLM

    history = [
        {"role": "user", "content": "Meri salary kyun kata?"},
        {"role": "assistant", "content": "Teen absence ki wajah se kata."},
    ]
    msg = BaseLLM._build_user_message("Aur kuch?", conversation_history=history)
    assert "Meri salary kyun kata?" in msg
    assert "Teen absence" in msg
    assert "User:" in msg
    assert "bhAI:" in msg


def test_build_user_message_new_session_marker():
    from src.bhai.llm.base import BaseLLM

    msg = BaseLLM._build_user_message("Hello", is_new_session=True)
    assert "Nayi conversation" in msg


def test_build_user_message_no_new_session_marker_by_default():
    from src.bhai.llm.base import BaseLLM

    msg = BaseLLM._build_user_message("Hello")
    assert "Nayi conversation" not in msg


# ── System Prompt Building ────────────────────────────────────────────────

def test_build_system_prompt_includes_user_profile(tmp_path):
    llm = _make_llm(tmp_path)
    profile = "Naam: Yashoda. Production team mein hai. 2022 se Tiny mein hai."
    prompt = llm._build_system_prompt("hr_admin", user_profile=profile)
    assert profile in prompt


def test_build_system_prompt_includes_memory_summary(tmp_path):
    llm = _make_llm(tmp_path)
    summary = "Pichle mahine 3 absences thi salary kata tha."
    prompt = llm._build_system_prompt("hr_admin", memory_summary=summary)
    assert summary in prompt


def test_build_system_prompt_includes_extracted_facts(tmp_path):
    llm = _make_llm(tmp_path)
    facts = "- Bete ki tabiyat kharab thi\n- Salary kata tha"
    prompt = llm._build_system_prompt("hr_admin", extracted_facts=facts)
    assert "Bete ki tabiyat" in prompt


def test_build_system_prompt_contains_personality_instruction(tmp_path):
    llm = _make_llm(tmp_path)
    prompt = llm._build_system_prompt("hr_admin")
    assert "bhAI" in prompt
    assert "ESCALATE" in prompt


def test_build_system_prompt_empty_profile_not_injected(tmp_path):
    llm = _make_llm(tmp_path)
    prompt = llm._build_system_prompt("hr_admin", user_profile="")
    assert "=== User Profile ===" not in prompt


def test_load_user_profile_missing_file_returns_empty(tmp_path):
    llm = _make_llm(tmp_path)
    profile = llm.load_user_profile("+919999999999")
    assert profile == ""


def test_load_user_profile_existing_file(tmp_path):
    users_dir = tmp_path / "users"
    users_dir.mkdir()
    phone = "+919876543210"
    profile_text = "Naam: Yashoda\nDepartment: production"
    (users_dir / f"{phone}.md").write_text(profile_text, encoding="utf-8")

    llm = _make_llm(tmp_path)
    loaded = llm.load_user_profile(phone)
    assert loaded == profile_text
