"""
Tests for inference/webhooks/telegram_webhook.py

Tests focus on the pure utility functions and webhook auth — all testable
without starting the full FastAPI app or any external services.
"""

import asyncio
import hashlib
import time
from unittest.mock import MagicMock

import pytest

# Import standalone functions directly to avoid triggering the full app lifespan
from inference.webhooks.telegram_webhook import (
    MAX_TTS_CHARS,
    RE_ONBOARDING_INSTRUCTION,
    _build_intro,
    _check_dashboard_key,
    _check_rate_limit,
    _detect_greeting,
    _ensure_webhook_registered,
    _extract_phone_numbers,
    _phone_hash,
    _rate_limit,
    _resolve_public_url,
    _split_for_tts,
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


# ── _build_intro: TTS-backend conditional ────────────────────────────


class _StubConfig:
    def __init__(self, tts_backend: str):
        self.tts_backend = tts_backend


def test_build_intro_omits_vidhi_clause_on_sarvam():
    """Sarvam voice — the 'Vidhi ki awaaz' line is wrong; drop it."""
    intro = _build_intro(_StubConfig("sarvam"))
    assert "विधी की आवाज़" not in intro
    assert "मैं भाई हूँ" in intro
    assert "आपका नाम क्या है?" in intro


def test_build_intro_includes_vidhi_clause_on_elevenlabs():
    """ElevenLabs uses Vidhi's cloned voice — clause should reappear."""
    intro = _build_intro(_StubConfig("elevenlabs"))
    assert "विधी की आवाज़" in intro
    assert "मैं भाई हूँ" in intro


# ── Re-onboarding instruction ────────────────────────────────────────


def test_re_onboarding_instruction_demands_recall_and_followup():
    """The re-onboarding hint must instruct the LLM to recall + follow up."""
    text = RE_ONBOARDING_INSTRUCTION
    assert "Re-onboarding Moment" in text
    assert "/start" in text
    # Three core asks the user wanted: nod recall, reference one thing, ask
    # one follow-up.
    assert (
        "remember" in text.lower() or "याद" in text or "remember them" in text.lower()
    )
    assert "follow-up" in text.lower() or "follow up" in text.lower()
    assert "No markdown" in text or "no markdown" in text.lower()


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


# ── Public URL resolution ────────────────────────────────────────────


class _UrlConfig:
    def __init__(self, webhook_public_url="", railway_public_domain=""):
        self.webhook_public_url = webhook_public_url
        self.railway_public_domain = railway_public_domain


def test_resolve_public_url_prefers_explicit_over_railway():
    """WEBHOOK_PUBLIC_URL wins when both are set."""
    cfg = _UrlConfig(
        webhook_public_url="https://custom.example.com",
        railway_public_domain="bhaivoicebot-production.up.railway.app",
    )
    assert _resolve_public_url(cfg) == "https://custom.example.com"


def test_resolve_public_url_uses_railway_domain_when_no_override():
    """RAILWAY_PUBLIC_DOMAIN is auto-injected — use it directly with https://."""
    cfg = _UrlConfig(railway_public_domain="bhaivoicebot-production.up.railway.app")
    assert _resolve_public_url(cfg) == "https://bhaivoicebot-production.up.railway.app"


def test_resolve_public_url_strips_trailing_slash():
    """Defensive: callers append /telegram/webhook so trailing slash would double-up."""
    cfg = _UrlConfig(webhook_public_url="https://custom.example.com/")
    assert _resolve_public_url(cfg) == "https://custom.example.com"


def test_resolve_public_url_returns_none_when_unconfigured():
    cfg = _UrlConfig()
    assert _resolve_public_url(cfg) is None


# ── _ensure_webhook_registered ────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_webhook_backoff_state():
    """Clear module-level backoff state between tests."""
    import inference.webhooks.telegram_webhook as mod

    mod._webhook_register_failures = 0
    mod._webhook_backoff_until = 0.0
    yield
    mod._webhook_register_failures = 0
    mod._webhook_backoff_until = 0.0


def _mock_client_with_url(current_url: str, last_error_message: str | None = None):
    client = MagicMock()
    result = {"url": current_url}
    if last_error_message:
        result["last_error_message"] = last_error_message
    client.get_webhook_info.return_value = {"ok": True, "result": result}
    client.set_webhook.return_value = {"ok": True, "result": True}
    return client


def test_ensure_webhook_skips_when_already_correct():
    """No-op when Telegram already points at the expected URL."""
    expected = "https://bot.example.com/telegram/webhook"
    client = _mock_client_with_url(expected)

    acted = _ensure_webhook_registered(client, expected, secret_token="s3cret")

    assert acted is False
    client.set_webhook.assert_not_called()


def test_ensure_webhook_re_registers_when_url_empty():
    """The actual outage we hit — `url: ""` — gets self-healed."""
    expected = "https://bot.example.com/telegram/webhook"
    client = _mock_client_with_url("")

    acted = _ensure_webhook_registered(client, expected, secret_token="s3cret")

    assert acted is True
    client.set_webhook.assert_called_once_with(
        url=expected,
        secret_token="s3cret",
        allowed_updates=["message", "edited_message"],
    )


def test_ensure_webhook_re_registers_when_url_drifts():
    """If somebody pointed Telegram at a stale URL, we correct it."""
    expected = "https://bot.example.com/telegram/webhook"
    client = _mock_client_with_url("https://stale.example.com/telegram/webhook")

    acted = _ensure_webhook_registered(client, expected, secret_token=None)

    assert acted is True
    client.set_webhook.assert_called_once()
    kwargs = client.set_webhook.call_args.kwargs
    assert kwargs["url"] == expected
    assert kwargs["secret_token"] is None  # explicit none → not registered with secret


def test_ensure_webhook_re_registers_when_last_error_present():
    """Even if URL matches, a recent last_error_message means Telegram is failing
    to deliver — re-register anyway as a defensive recovery."""
    expected = "https://bot.example.com/telegram/webhook"
    client = _mock_client_with_url(expected, last_error_message="403 Forbidden")

    acted = _ensure_webhook_registered(client, expected, secret_token="s3cret")

    assert acted is True
    client.set_webhook.assert_called_once()


def test_ensure_webhook_backs_off_after_repeated_failures():
    """3 consecutive setWebhook failures → 1h backoff window."""
    import inference.webhooks.telegram_webhook as mod

    expected = "https://bot.example.com/telegram/webhook"
    client = _mock_client_with_url("")
    client.set_webhook.side_effect = RuntimeError("Telegram API down")

    for _ in range(3):
        _ensure_webhook_registered(client, expected, secret_token=None)

    assert mod._webhook_register_failures == 3
    assert mod._webhook_backoff_until > time.time()

    # Next call within backoff window does nothing — get_webhook_info not even hit
    client.get_webhook_info.reset_mock()
    acted = _ensure_webhook_registered(client, expected, secret_token=None)
    assert acted is False
    client.get_webhook_info.assert_not_called()


# ── /admin/send-message validation ───────────────────────────────────


def test_admin_send_message_rejects_bad_key():
    """Wrong dashboard key returns 401 without touching Telegram."""
    from inference.webhooks.telegram_webhook import admin_send_message

    result = asyncio.run(
        admin_send_message(phone_hash="abc123def456", key="wrong", text="hi")
    )
    assert result.status_code == 401


def test_admin_send_message_rejects_empty_text():
    """Empty text payload returns 400 with a clear error."""
    from inference.webhooks.telegram_webhook import (
        _DASHBOARD_KEY,
        admin_send_message,
    )

    result = asyncio.run(
        admin_send_message(phone_hash="abc123def456", key=_DASHBOARD_KEY, text="")
    )
    assert result.status_code == 400


def test_admin_send_message_rejects_whitespace_only_text():
    """Whitespace-only text is treated as empty (no accidentally-blank corrections)."""
    from inference.webhooks.telegram_webhook import (
        _DASHBOARD_KEY,
        admin_send_message,
    )

    result = asyncio.run(
        admin_send_message(
            phone_hash="abc123def456", key=_DASHBOARD_KEY, text="   \n  "
        )
    )
    assert result.status_code == 400
