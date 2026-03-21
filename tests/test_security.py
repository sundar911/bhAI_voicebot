"""
Tests for security layer: Fernet crypto, Twilio signature verification,
per-user rate limiting, and path traversal protection logic.

No external services required.
"""

from pathlib import Path

import pytest
from cryptography.fernet import Fernet, InvalidToken
from twilio.request_validator import RequestValidator

# ── Crypto ───────────────────────────────────────────────────────────────

def test_encrypt_decrypt_roundtrip():
    from src.bhai.security.crypto import decrypt_text, encrypt_text

    original = "Yashoda ki salary teen absence se kata."
    assert decrypt_text(encrypt_text(original)) == original


def test_encrypt_produces_different_ciphertext_each_time():
    from src.bhai.security.crypto import encrypt_text

    text = "same plaintext"
    # Fernet uses a random IV, so two encryptions must differ
    assert encrypt_text(text) != encrypt_text(text)


def test_decrypt_wrong_key_raises():
    from src.bhai.security.crypto import encrypt_text

    encrypted = encrypt_text("secret message")

    wrong_key = Fernet.generate_key()
    f = Fernet(wrong_key)
    with pytest.raises(InvalidToken):
        f.decrypt(encrypted.encode())


def test_encrypt_decrypt_hindi_text():
    from src.bhai.security.crypto import decrypt_text, encrypt_text

    hindi = "नमस्ते, मेरी salary क्यों कम आई? मुझे समझाओ।"
    assert decrypt_text(encrypt_text(hindi)) == hindi


def test_encrypt_decrypt_empty_string():
    from src.bhai.security.crypto import decrypt_text, encrypt_text

    assert decrypt_text(encrypt_text("")) == ""


# ── Twilio Signature Verification ────────────────────────────────────────

_AUTH_TOKEN = "test_auth_token_32chars_long_pad"
_WEBHOOK_URL = "https://test.ngrok.app/webhook"
_TEST_PARAMS = {
    "Body": "Namaste",
    "From": "whatsapp:+919876543210",
    "NumMedia": "0",
}


def _valid_signature(auth_token=_AUTH_TOKEN, url=_WEBHOOK_URL, params=_TEST_PARAMS):
    return RequestValidator(auth_token).compute_signature(url, params)


def test_verify_valid_signature():
    from src.bhai.security.webhook_auth import verify_twilio_signature

    sig = _valid_signature()
    assert verify_twilio_signature(_AUTH_TOKEN, _WEBHOOK_URL, _TEST_PARAMS, sig) is True


def test_verify_invalid_signature():
    from src.bhai.security.webhook_auth import verify_twilio_signature

    assert verify_twilio_signature(_AUTH_TOKEN, _WEBHOOK_URL, _TEST_PARAMS, "bad_sig") is False


def test_verify_missing_signature_returns_false():
    from src.bhai.security.webhook_auth import verify_twilio_signature

    assert verify_twilio_signature(_AUTH_TOKEN, _WEBHOOK_URL, _TEST_PARAMS, "") is False


def test_verify_wrong_url_returns_false():
    from src.bhai.security.webhook_auth import verify_twilio_signature

    sig = _valid_signature()
    assert verify_twilio_signature(_AUTH_TOKEN, "https://evil.com/webhook", _TEST_PARAMS, sig) is False


def test_verify_wrong_auth_token_returns_false():
    from src.bhai.security.webhook_auth import verify_twilio_signature

    sig = _valid_signature()
    assert verify_twilio_signature("wrong_token_here_xxxxxxxxxxx", _WEBHOOK_URL, _TEST_PARAMS, sig) is False


# ── Per-user Rate Limiting ────────────────────────────────────────────────

def test_rate_limit_allows_requests_under_limit():
    import inference.webhooks.twilio_webhook as wh

    wh._rate_limit.clear()
    phone = "+919000000001"
    for _ in range(10):
        assert wh._check_rate_limit(phone) is True


def test_rate_limit_blocks_at_limit():
    import inference.webhooks.twilio_webhook as wh

    wh._rate_limit.clear()
    phone = "+919000000002"
    for _ in range(10):
        wh._check_rate_limit(phone)
    # 11th request in the same window must be blocked
    assert wh._check_rate_limit(phone) is False


def test_rate_limit_different_phones_are_independent():
    import inference.webhooks.twilio_webhook as wh

    wh._rate_limit.clear()
    phone_a = "+919000000003"
    phone_b = "+919000000004"

    for _ in range(10):
        wh._check_rate_limit(phone_a)

    # phone_a is limited but phone_b should still pass
    assert wh._check_rate_limit(phone_a) is False
    assert wh._check_rate_limit(phone_b) is True


# ── Path Traversal Protection Logic ──────────────────────────────────────

def test_traversal_check_blocks_parent_escape():
    """Verify the path resolution logic blocks paths that escape the serve dir."""
    serve_dir = Path("/tmp/bhai_audio_test_abc123")
    malicious = (serve_dir / "../../.env").resolve()
    assert not str(malicious).startswith(str(serve_dir.resolve()))


def test_traversal_check_allows_valid_filename():
    """Valid filenames within the serve dir must pass."""
    serve_dir = Path("/tmp/bhai_audio_test_abc123")
    valid = (serve_dir / "response_twilio_12345.ogg").resolve()
    assert str(valid).startswith(str(serve_dir.resolve()))
