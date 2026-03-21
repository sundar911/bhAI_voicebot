"""
Tests for inference/webhooks/twilio_webhook.py

Tests focus on the pure utility functions (rate limiting, phone hashing)
and the Twilio signature verification helper — all testable without
starting the full FastAPI app or any external services.
"""

import hashlib
import time
from unittest.mock import MagicMock, patch

import pytest

from bhai.security.webhook_auth import verify_twilio_signature

# Import standalone functions directly to avoid triggering the full app lifespan
from inference.webhooks.twilio_webhook import (
    _check_rate_limit,
    _phone_hash,
    _rate_limit,
    _twiml_empty,
)


@pytest.fixture(autouse=True)
def clear_rate_limit_state():
    """Reset global rate-limit dict before and after every test."""
    _rate_limit.clear()
    yield
    _rate_limit.clear()


# ── _phone_hash ────────────────────────────────────────────────────────


def test_phone_hash_returns_12_chars():
    assert len(_phone_hash("+919876543210")) == 12


def test_phone_hash_is_deterministic():
    assert _phone_hash("+91111") == _phone_hash("+91111")


def test_phone_hash_different_inputs():
    assert _phone_hash("+91111") != _phone_hash("+91222")


def test_phone_hash_no_pii_in_output():
    """The phone number itself should not appear in the hash."""
    result = _phone_hash("+919876543210")
    assert "9876543210" not in result


# ── _check_rate_limit ─────────────────────────────────────────────────


def test_rate_limit_allows_first_request():
    assert _check_rate_limit("+91aaa") is True


def test_rate_limit_allows_up_to_max():
    phone = "+91bbb"
    # RATE_LIMIT_MAX is 10
    for _ in range(10):
        assert _check_rate_limit(phone) is True


def test_rate_limit_blocks_after_max():
    phone = "+91ccc"
    for _ in range(10):
        _check_rate_limit(phone)
    # 11th request should be blocked
    assert _check_rate_limit(phone) is False


def test_rate_limit_window_expires():
    """Old timestamps outside the window are purged, allowing new requests."""
    phone = "+91ddd"
    # Manually inject 10 old timestamps (outside the 60-second window)
    _rate_limit[phone] = [time.time() - 120] * 10

    # First real request should succeed (old ones purged)
    assert _check_rate_limit(phone) is True


# ── verify_twilio_signature ────────────────────────────────────────────


def test_signature_empty_string_rejected():
    """Empty signature header returns False immediately."""
    result = verify_twilio_signature(
        auth_token="test_token",
        url="https://example.com/webhook",
        params={"From": "whatsapp:+91111"},
        signature="",
    )
    assert result is False


def test_signature_valid_with_known_vector():
    """
    Verify that a correctly computed Twilio signature passes validation.

    We compute the expected signature using the same algorithm Twilio uses,
    then verify it — this is a self-consistent round-trip test.
    """
    import base64
    import hmac

    auth_token = "test_secret_token_123"
    url = "https://mybot.ngrok.app/webhook"
    params = {
        "From": "whatsapp:+911234567890",
        "Body": "hello",
        "NumMedia": "0",
    }

    # Build the string Twilio signs (URL + sorted params)
    s = url
    for key in sorted(params.keys()):
        s += key + params[key]

    # Compute expected HMAC-SHA1
    mac = hmac.new(auth_token.encode("utf-8"), s.encode("utf-8"), "sha1")
    expected_sig = base64.b64encode(mac.digest()).decode("utf-8")

    result = verify_twilio_signature(auth_token, url, params, expected_sig)
    assert result is True


def test_signature_invalid_rejected():
    """A garbage signature is rejected."""
    result = verify_twilio_signature(
        auth_token="real_token",
        url="https://example.com/webhook",
        params={"From": "whatsapp:+91111"},
        signature="definitely_not_valid",
    )
    assert result is False


# ── _twiml_empty ──────────────────────────────────────────────────────


def test_twiml_empty_response():
    """_twiml_empty returns a 200 XML response."""
    resp = _twiml_empty()
    assert resp.status_code == 200
    assert b"<Response>" in resp.body
    assert resp.media_type == "application/xml"


# ── /health endpoint ──────────────────────────────────────────────────


def test_health_endpoint():
    """health() returns the expected JSON structure (tested directly)."""
    import asyncio

    from inference.webhooks.twilio_webhook import health

    result = asyncio.run(health())
    assert result == {"status": "healthy", "service": "bhai-twilio-webhook"}
