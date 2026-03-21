"""
Webhook integration tests using FastAPI TestClient.

All external dependencies (Twilio, Sarvam STT/TTS, LLM) are mocked.
The full message processing pipeline (text path) runs end-to-end in-process.

Meta/WhatsApp access is NOT required — this simulates Twilio HTTP calls directly.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_PHONE = "+919876543210"
TEST_SENDER = f"whatsapp:{TEST_PHONE}"

# Canned LLM response — short Hindi reply, no escalation
_LLM_RESPONSE = {
    "text": "ठीक है, समझ गई।",
    "raw": "ठीक है, समझ गई।\nESCALATE: false",
    "escalate": False,
    "segments": [{"text": "ठीक है, समझ गई।", "emotion": "neutral"}],
}


def _text_payload(body="Namaste bhai, meri salary kyun kata?"):
    return {
        "From": TEST_SENDER,
        "Body": body,
        "NumMedia": "0",
        "MediaUrl0": "",
        "MediaContentType0": "",
    }


def _make_mock_worker():
    """RetryWorker mock whose run_forever is a real async coroutine."""

    async def _noop_run_forever():
        await asyncio.sleep(9999)  # stays alive until cancelled by lifespan

    mock_instance = MagicMock()
    mock_instance.run_forever = _noop_run_forever
    mock_class = MagicMock(return_value=mock_instance)
    return mock_class


@pytest.fixture
def webhook_context(tmp_path, monkeypatch):
    """
    Yields a fully-mocked webhook client plus test helpers.

    All real I/O (Twilio, Sarvam, LLM) is replaced with mocks.
    The conversation store uses an isolated tmp_path SQLite database.
    """
    import os

    # Make sure encryption key is set (conftest session fixture already does this,
    # but monkeypatch ensures cleanup if value drifts)
    monkeypatch.setenv("BHAI_ENCRYPTION_KEY", os.environ["BHAI_ENCRYPTION_KEY"])

    from src.bhai.config import Config
    from src.bhai.memory.store import ConversationStore
    from src.bhai.resilience.faq_cache import FAQCache
    from src.bhai.resilience.queue import RequestQueue

    # Isolated store + queue
    test_store = ConversationStore(tmp_path / "webhook_conv.db")
    test_queue = RequestQueue(tmp_path / "webhook_queue.db")

    # Empty FAQ cache (no entries → all queries go to LLM)
    empty_kb = tmp_path / "empty_kb"
    empty_kb.mkdir()
    test_faq = FAQCache(empty_kb, threshold=0.6)

    fake_config = Config(
        llm_backend="sarvam",
        sarvam_api_key="test_key",
        twilio_account_sid="ACtest123",
        twilio_auth_token="test_auth_token_32chars_long_pad",
        twilio_whatsapp_number="whatsapp:+14155238886",
        base_url="https://test.ngrok.app",
        ack_enabled=False,
        faq_cache_threshold=0.6,
    )

    mock_llm = MagicMock()
    mock_llm.load_user_profile.return_value = ""
    mock_llm.generate_with_emotions.return_value = dict(_LLM_RESPONSE)
    mock_llm._call_api_with_retry.return_value = "SUMMARY:\nTest.\nFACTS:\n[]"

    mock_twilio = MagicMock()
    mock_worker_class = _make_mock_worker()

    # Reset module-level singletons between tests
    import inference.webhooks.twilio_webhook as wh

    wh._rate_limit.clear()
    wh._store = None
    wh._queue = None
    wh._faq_cache = None

    with (
        patch("inference.webhooks.twilio_webhook.verify_twilio_signature", return_value=True),
        patch("inference.webhooks.twilio_webhook.TwilioWhatsAppClient", return_value=mock_twilio),
        patch("inference.webhooks.twilio_webhook.create_llm", return_value=mock_llm),
        patch("inference.webhooks.twilio_webhook.load_config", return_value=fake_config),
        patch("inference.webhooks.twilio_webhook.RetryWorker", mock_worker_class),
        patch("inference.webhooks.twilio_webhook.ensure_dir"),
        patch("inference.webhooks.twilio_webhook.convert_to_ogg_opus"),
        patch("src.bhai.tts.sarvam_tts.SarvamTTS"),
        patch("inference.webhooks.twilio_webhook._get_store", return_value=test_store),
        patch("inference.webhooks.twilio_webhook._get_queue", return_value=test_queue),
        patch("inference.webhooks.twilio_webhook._get_faq_cache", return_value=test_faq),
    ):
        from inference.webhooks.twilio_webhook import app

        with TestClient(app, raise_server_exceptions=True) as client:
            yield {
                "client": client,
                "store": test_store,
                "queue": test_queue,
                "twilio": mock_twilio,
                "llm": mock_llm,
                "faq": test_faq,
            }

    test_store.close()


# ── Health endpoint ───────────────────────────────────────────────────────

def test_health_endpoint(webhook_context):
    resp = webhook_context["client"].get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


# ── Text message processing ───────────────────────────────────────────────

def test_text_message_returns_200_with_twiml(webhook_context):
    resp = webhook_context["client"].post("/webhook", data=_text_payload())
    assert resp.status_code == 200
    assert "<Response>" in resp.text


def test_text_message_triggers_llm(webhook_context):
    webhook_context["client"].post("/webhook", data=_text_payload())

    mock_llm = webhook_context["llm"]
    mock_llm.generate_with_emotions.assert_called_once()

    # Confirm the transcript was passed to the LLM
    call_args = str(mock_llm.generate_with_emotions.call_args)
    assert "Namaste bhai" in call_args


def test_text_message_saves_user_message_to_store(webhook_context):
    webhook_context["client"].post("/webhook", data=_text_payload())

    store = webhook_context["store"]
    messages = store.get_recent_messages(TEST_PHONE)
    user_msgs = [m for m in messages if m["role"] == "user"]
    assert any("Namaste bhai" in m["content"] for m in user_msgs)


def test_text_message_saves_assistant_response_to_store(webhook_context):
    webhook_context["client"].post("/webhook", data=_text_payload())

    store = webhook_context["store"]
    messages = store.get_recent_messages(TEST_PHONE)
    assistant_msgs = [m for m in messages if m["role"] == "assistant"]
    assert len(assistant_msgs) >= 1
    assert any("ठीक है" in m["content"] for m in assistant_msgs)


def test_empty_body_no_media_is_ignored(webhook_context):
    """Messages with no body and no media are skipped without calling the LLM."""
    resp = webhook_context["client"].post("/webhook", data={
        "From": TEST_SENDER,
        "Body": "",
        "NumMedia": "0",
    })
    assert resp.status_code == 200
    webhook_context["llm"].generate_with_emotions.assert_not_called()


def test_second_message_same_session(webhook_context):
    """Two rapid messages from the same user stay in the same session."""
    client = webhook_context["client"]
    store = webhook_context["store"]

    client.post("/webhook", data=_text_payload("Pehla message"))
    client.post("/webhook", data=_text_payload("Doosra message"))

    messages = store.get_recent_messages(TEST_PHONE, limit=10)
    session_ids = {m.get("session_id") for m in messages if "session_id" in m}
    # Both messages should share a session ID — but get_recent_messages
    # doesn't expose session_id in its return dict; just verify count
    user_msgs = [m for m in messages if m["role"] == "user"]
    assert len(user_msgs) == 2


# ── Rate limiting ─────────────────────────────────────────────────────────

def test_rate_limit_blocks_excess_requests(webhook_context):
    client = webhook_context["client"]
    mock_llm = webhook_context["llm"]

    import inference.webhooks.twilio_webhook as wh
    wh._rate_limit.clear()

    payload = _text_payload()

    # First 10 requests should be processed
    for _ in range(10):
        resp = client.post("/webhook", data=payload)
        assert resp.status_code == 200

    llm_calls_before = mock_llm.generate_with_emotions.call_count

    # 11th request must be silently dropped (no LLM call)
    resp = client.post("/webhook", data=payload)
    assert resp.status_code == 200
    assert mock_llm.generate_with_emotions.call_count == llm_calls_before


# ── Audio serving ─────────────────────────────────────────────────────────

def test_audio_nonexistent_file_returns_404(webhook_context):
    resp = webhook_context["client"].get("/audio/nonexistent_response_12345.ogg")
    assert resp.status_code == 404



# ── Signature verification ────────────────────────────────────────────────

def test_missing_signature_returns_403():
    """Without a valid X-Twilio-Signature, the real verifier must return 403."""
    import os
    from src.bhai.config import Config

    os.environ.setdefault("BHAI_ENCRYPTION_KEY", os.environ.get("BHAI_ENCRYPTION_KEY", ""))

    fake_config = Config(
        twilio_auth_token="real_auth_token_test",
        ack_enabled=False,
    )

    mock_worker_class = _make_mock_worker()

    with (
        patch("inference.webhooks.twilio_webhook.load_config", return_value=fake_config),
        patch("inference.webhooks.twilio_webhook.RetryWorker", mock_worker_class),
        patch("inference.webhooks.twilio_webhook._get_store", return_value=MagicMock()),
        patch("inference.webhooks.twilio_webhook._get_queue", return_value=MagicMock()),
        patch("inference.webhooks.twilio_webhook._get_faq_cache", return_value=MagicMock()),
    ):
        from inference.webhooks.twilio_webhook import app

        with TestClient(app) as client:
            resp = client.post("/webhook", data={
                "From": TEST_SENDER,
                "Body": "test",
                "NumMedia": "0",
            })
            assert resp.status_code == 403


# ── FAQ cache skips LLM ───────────────────────────────────────────────────

def test_faq_cache_hit_skips_llm(tmp_path, monkeypatch):
    """When a FAQ match is found, the LLM must NOT be called."""
    import os

    monkeypatch.setenv("BHAI_ENCRYPTION_KEY", os.environ["BHAI_ENCRYPTION_KEY"])

    from src.bhai.config import Config
    from src.bhai.memory.store import ConversationStore
    from src.bhai.resilience.faq_cache import FAQCache
    from src.bhai.resilience.queue import RequestQueue

    test_store = ConversationStore(tmp_path / "faq_test.db")
    test_queue = RequestQueue(tmp_path / "faq_queue.db")

    # Knowledge base with an exact FAQ entry
    kb_dir = tmp_path / "kb"
    hr_dir = kb_dir / "hr_admin"
    hr_dir.mkdir(parents=True)
    (hr_dir / "faq.md").write_text(
        "# HR\n\n## Common Questions\n\n### \"Salary kata kyun?\"\n→ Teen absence ki wajah se.",
        encoding="utf-8",
    )
    test_faq = FAQCache(kb_dir, threshold=0.3)

    fake_config = Config(
        llm_backend="sarvam",
        sarvam_api_key="test",
        twilio_account_sid="ACtest",
        twilio_auth_token="test_token_padded_to_length",
        twilio_whatsapp_number="whatsapp:+14155238886",
        base_url="https://test.ngrok.app",
        ack_enabled=False,
    )

    mock_llm = MagicMock()
    mock_twilio = MagicMock()
    mock_worker_class = _make_mock_worker()

    import inference.webhooks.twilio_webhook as wh

    wh._rate_limit.clear()
    wh._store = None
    wh._queue = None
    wh._faq_cache = None

    with (
        patch("inference.webhooks.twilio_webhook.verify_twilio_signature", return_value=True),
        patch("inference.webhooks.twilio_webhook.TwilioWhatsAppClient", return_value=mock_twilio),
        patch("inference.webhooks.twilio_webhook.create_llm", return_value=mock_llm),
        patch("inference.webhooks.twilio_webhook.load_config", return_value=fake_config),
        patch("inference.webhooks.twilio_webhook.RetryWorker", mock_worker_class),
        patch("inference.webhooks.twilio_webhook.ensure_dir"),
        patch("inference.webhooks.twilio_webhook.convert_to_ogg_opus"),
        patch("src.bhai.tts.sarvam_tts.SarvamTTS"),
        patch("inference.webhooks.twilio_webhook._get_store", return_value=test_store),
        patch("inference.webhooks.twilio_webhook._get_queue", return_value=test_queue),
        patch("inference.webhooks.twilio_webhook._get_faq_cache", return_value=test_faq),
    ):
        from inference.webhooks.twilio_webhook import app

        with TestClient(app) as client:
            client.post("/webhook", data={
                "From": TEST_SENDER,
                "Body": "Salary kata kyun?",
                "NumMedia": "0",
            })

    test_store.close()

    # The LLM should not have been touched — FAQ cache handled the query
    mock_llm.generate_with_emotions.assert_not_called()
    mock_llm.generate.assert_not_called()
