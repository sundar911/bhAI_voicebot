"""
Tests for src/bhai/escalations/handler.py.

We use a StubEmailClient that records send() calls + return value so we
never actually talk to SMTP. The voice_sender callable is also stubbed —
it just records that it was invoked with the confirmation text.
"""

import asyncio
from pathlib import Path
from typing import List

import pytest

from bhai.config import Config
from bhai.escalations.handler import (
    CONFIRM_FAILURE_HI,
    CONFIRM_SUCCESS_HI,
    handle_escalation,
)
from bhai.memory.store import ConversationStore

# ── Stubs ─────────────────────────────────────────────────────────────


class StubEmailClient:
    """Records send() calls; returns from a queue of pre-set bools."""

    def __init__(self, results: List[bool]):
        self._results = list(results)
        self.calls: list[dict] = []

    async def send(self, to, subject, html_body):
        self.calls.append({"to": to, "subject": subject, "html_body": html_body})
        if self._results:
            return self._results.pop(0)
        return True


class RaisingEmailClient:
    """For the swallowed-exception test."""

    def __init__(self):
        self.calls = 0

    async def send(self, to, subject, html_body):
        self.calls += 1
        raise RuntimeError("smtp blew up")


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def voice_sender():
    """Replaces _synthesize_and_send_voice — records the kwargs it was called with."""
    calls: list[dict] = []

    def _send(**kwargs):
        calls.append(kwargs)
        return True

    _send.calls = calls  # type: ignore[attr-defined]
    return _send


@pytest.fixture
def telegram_client_stub():
    """A bare object — handler only passes it through to voice_sender."""

    class _TC:
        pass

    return _TC()


@pytest.fixture
def cfg_enabled():
    return Config(
        smtp_username="bhai@example.com",
        smtp_app_password="testpassword",
        escalation_from_email="bhai@example.com",
        escalation_recipients=("rishi@example.com", "anu@example.com"),
        escalation_enabled=True,
    )


@pytest.fixture
def cfg_disabled():
    return Config(escalation_enabled=False, escalation_recipients=())


@pytest.fixture
def store(tmp_path) -> ConversationStore:
    return ConversationStore(tmp_path / "test.db")


@pytest.fixture(autouse=True)
def patch_sleep(monkeypatch):
    """Skip the 30s retry wait in every test."""

    async def _no_sleep(_):
        return None

    monkeypatch.setattr("bhai.escalations.handler.asyncio.sleep", _no_sleep)


@pytest.fixture
def base_kwargs(store, voice_sender, telegram_client_stub, tmp_path):
    """The kwargs every handle_escalation call needs — tests override what they care about."""
    return dict(
        store=store,
        voice_sender=voice_sender,
        phone="tg_123456",
        chat_id=123456,
        phone_id="abc123def456",
        session_id="sess001",
        user_transcript="मुझे मदद चाहिए",
        bot_response="Main team ko email karne wali hoon.",
        recent_messages=[
            {"role": "user", "content": "hello", "timestamp": "2026-05-20T10:00"},
            {
                "role": "assistant",
                "content": "namaste!",
                "timestamp": "2026-05-20T10:00",
            },
        ],
        user_profile="",
        run_id="test_run_1",
        run_dir=tmp_path / "run",
        telegram_client=telegram_client_stub,
    )


# ── Disabled / no recipients short-circuits ───────────────────────────


@pytest.mark.asyncio
async def test_skips_when_escalation_disabled(cfg_disabled, base_kwargs):
    email_client = StubEmailClient(results=[True])
    await handle_escalation(
        config=cfg_disabled, email_client=email_client, **base_kwargs
    )
    assert email_client.calls == []
    assert base_kwargs["voice_sender"].calls == []  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_skips_when_no_recipients(base_kwargs):
    cfg = Config(escalation_enabled=True, escalation_recipients=())
    email_client = StubEmailClient(results=[True])
    await handle_escalation(config=cfg, email_client=email_client, **base_kwargs)
    assert email_client.calls == []


# ── Body composition ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_includes_recipients_and_subject(cfg_enabled, base_kwargs):
    email_client = StubEmailClient(results=[True])
    await handle_escalation(
        config=cfg_enabled, email_client=email_client, **base_kwargs
    )
    assert len(email_client.calls) == 1
    call = email_client.calls[0]
    assert call["to"] == ["rishi@example.com", "anu@example.com"]
    assert "bhAI escalation" in call["subject"]
    assert "user #" in call["subject"]


@pytest.mark.asyncio
async def test_body_contains_phone_and_triggering_turn(cfg_enabled, base_kwargs):
    email_client = StubEmailClient(results=[True])
    await handle_escalation(
        config=cfg_enabled, email_client=email_client, **base_kwargs
    )
    body = email_client.calls[0]["html_body"]
    assert "tg_123456" in body
    assert "मुझे मदद चाहिए" in body  # escaped via html.escape but devnagari survives
    assert "Main team ko email karne wali hoon." in body


@pytest.mark.asyncio
async def test_body_contains_recent_messages(cfg_enabled, base_kwargs):
    email_client = StubEmailClient(results=[True])
    await handle_escalation(
        config=cfg_enabled, email_client=email_client, **base_kwargs
    )
    body = email_client.calls[0]["html_body"]
    assert "namaste!" in body
    assert "Recent conversation" in body


# ── Success path: confirmation voice ─────────────────────────────────


@pytest.mark.asyncio
async def test_success_triggers_success_confirmation_voice(cfg_enabled, base_kwargs):
    email_client = StubEmailClient(results=[True])
    await handle_escalation(
        config=cfg_enabled, email_client=email_client, **base_kwargs
    )
    voice_calls = base_kwargs["voice_sender"].calls  # type: ignore[attr-defined]
    assert len(voice_calls) == 1
    assert voice_calls[0]["text"] == CONFIRM_SUCCESS_HI


@pytest.mark.asyncio
async def test_confirmation_message_persisted_to_store(cfg_enabled, base_kwargs):
    email_client = StubEmailClient(results=[True])
    await handle_escalation(
        config=cfg_enabled, email_client=email_client, **base_kwargs
    )
    recent = base_kwargs["store"].get_recent_messages("tg_123456", limit=5)
    assistant_msgs = [m for m in recent if m["role"] == "assistant"]
    assert any(m["content"] == CONFIRM_SUCCESS_HI for m in assistant_msgs)


# ── Retry behaviour ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retries_once_on_first_failure(cfg_enabled, base_kwargs):
    email_client = StubEmailClient(results=[False, True])
    await handle_escalation(
        config=cfg_enabled, email_client=email_client, **base_kwargs
    )
    assert len(email_client.calls) == 2
    voice_calls = base_kwargs["voice_sender"].calls  # type: ignore[attr-defined]
    assert voice_calls[-1]["text"] == CONFIRM_SUCCESS_HI


@pytest.mark.asyncio
async def test_both_attempts_fail_sends_failure_voice(cfg_enabled, base_kwargs):
    email_client = StubEmailClient(results=[False, False])
    await handle_escalation(
        config=cfg_enabled, email_client=email_client, **base_kwargs
    )
    assert len(email_client.calls) == 2
    voice_calls = base_kwargs["voice_sender"].calls  # type: ignore[attr-defined]
    assert voice_calls[-1]["text"] == CONFIRM_FAILURE_HI
    # The failure message is also persisted
    recent = base_kwargs["store"].get_recent_messages("tg_123456", limit=5)
    assert any(m["content"] == CONFIRM_FAILURE_HI for m in recent)


@pytest.mark.asyncio
async def test_voice_sender_failure_does_not_propagate(cfg_enabled, base_kwargs):
    """If TTS blows up, handle_escalation should still complete cleanly."""

    def _exploding_sender(**kwargs):
        raise RuntimeError("tts is on fire")

    base_kwargs["voice_sender"] = _exploding_sender
    email_client = StubEmailClient(results=[True])
    # Must not raise
    await handle_escalation(
        config=cfg_enabled, email_client=email_client, **base_kwargs
    )
    assert len(email_client.calls) == 1
