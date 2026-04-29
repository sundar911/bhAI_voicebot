"""
Tests for inference/webhooks/telegram_webhook.py

Tests focus on the pure utility functions and webhook auth — all testable
without starting the full FastAPI app or any external services.
"""

import asyncio
import hashlib
import time

import pytest

# Import standalone functions directly to avoid triggering the full app lifespan
from inference.webhooks.telegram_webhook import (
    _check_dashboard_key,
    _check_rate_limit,
    _detect_greeting,
    _extract_phone_numbers,
    _phone_hash,
    _rate_limit,
    _split_for_tts,
    MAX_TTS_CHARS,
)


@pytest.fixture(autouse=True)
def clear_rate_limit_state():
    """Reset global rate-limit dict before and after every test."""
    _rate_limit.clear()
    yield
    _rate_limit.clear()


# ── Identifier hashing ────────────────────────────────────────────────


def test_phone_hash_works_for_telegram_identifier():
    """tg_<chat_id> identifier hashes consistently."""
    assert len(_phone_hash("tg_123456789")) == 12


def test_phone_hash_telegram_differs_from_twilio():
    """Same digits as Twilio phone produce a different hash with tg_ prefix."""
    assert _phone_hash("tg_9876543210") != _phone_hash("9876543210")


# ── Rate limiting ────────────────────────────────────────────────────


def test_rate_limit_allows_first_request_for_telegram_user():
    assert _check_rate_limit("tg_111") is True


def test_rate_limit_blocks_after_max_for_telegram_user():
    phone = "tg_222"
    for _ in range(10):
        _check_rate_limit(phone)
    assert _check_rate_limit(phone) is False


def test_rate_limit_window_expires_for_telegram_user():
    phone = "tg_333"
    _rate_limit[phone] = [time.time() - 120] * 10
    assert _check_rate_limit(phone) is True


# ── Greeting detection (handles /start) ──────────────────────────────


def test_detect_greeting_recognises_start_command():
    """Telegram /start should be treated as a greeting."""
    assert _detect_greeting("/start") == "/start"


def test_detect_greeting_recognises_namaste():
    assert _detect_greeting("namaste") == "namaste"


def test_detect_greeting_returns_none_for_long_message():
    # Message > 50 chars is not treated as a pure greeting even if it starts with one
    assert (
        _detect_greeting(
            "hello there, I need help with applying for my voter ID this week"
        )
        is None
    )


def test_detect_greeting_returns_none_for_non_greeting():
    assert _detect_greeting("मेरा नाम सुंदर है") is None


def test_detect_greeting_returns_none_for_empty():
    assert _detect_greeting("") is None
    assert _detect_greeting("   ") is None


# ── TTS chunking ─────────────────────────────────────────────────────


def test_split_for_tts_returns_single_chunk_for_short_text():
    text = "नमस्ते भाई"
    assert _split_for_tts(text) == [text]


def test_split_for_tts_breaks_long_text_at_sentence_boundary():
    sentence = "ये एक वाक्य है। "
    text = sentence * 30  # ~480 chars, well over MAX_TTS_CHARS
    chunks = _split_for_tts(text)
    assert len(chunks) > 1
    # Every chunk must respect the limit
    for chunk in chunks:
        assert len(chunk) <= MAX_TTS_CHARS


# ── Phone number extraction ──────────────────────────────────────────


def test_extract_phone_numbers_returns_none_when_no_number():
    text = "अच्छा, कहाँ रहते हो?"
    voice_text, contact_msg = _extract_phone_numbers(text)
    assert voice_text == text
    assert contact_msg is None


def test_extract_phone_numbers_strips_known_contact():
    text = "Vijay को call करो: 9321125042"
    voice_text, contact_msg = _extract_phone_numbers(text)
    assert "9321125042" not in voice_text
    assert contact_msg is not None
    assert "9321125042" in contact_msg
    assert "Vijay" in contact_msg


# ── Dashboard auth ───────────────────────────────────────────────────


def test_dashboard_key_rejects_empty():
    result = _check_dashboard_key("")
    assert result is not None
    assert result.status_code == 401


def test_dashboard_key_rejects_wrong():
    result = _check_dashboard_key("wrong-key")
    assert result is not None
    assert result.status_code == 401


def test_dashboard_key_accepts_correct():
    from inference.webhooks.telegram_webhook import _DASHBOARD_KEY

    result = _check_dashboard_key(_DASHBOARD_KEY)
    assert result is None


# ── /health endpoint ─────────────────────────────────────────────────


def test_health_endpoint():
    from inference.webhooks.telegram_webhook import health

    result = asyncio.run(health())
    assert result == {"status": "healthy", "service": "bhai-telegram-webhook"}


# ── TelegramClient — basic shape (no network) ─────────────────────────


def test_telegram_client_requires_token():
    from src.bhai.integrations.telegram_client import TelegramClient

    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        TelegramClient(bot_token="")


def test_telegram_client_builds_api_urls():
    from src.bhai.integrations.telegram_client import TelegramClient

    client = TelegramClient(bot_token="123:ABC")
    assert client.api_base == "https://api.telegram.org/bot123:ABC"
    assert client.file_base == "https://api.telegram.org/file/bot123:ABC"
