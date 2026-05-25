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
        gmail_client_id="test-client-id.apps.googleusercontent.com",
        gmail_client_secret="GOCSPX-test-secret",
        gmail_refresh_token="1//test-refresh-token",
        gmail_sender_email="bhai@example.com",
        escalation_recipients=("rishi@example.com", "anu@example.com"),
        escalation_recipients_docs_bc=("priti@example.com",),
        escalation_recipients_docs_midc=("dinesh@example.com",),
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


# ── Category-based routing ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_category_none_routes_to_default_grievance_recipients(
    cfg_enabled, base_kwargs
):
    email_client = StubEmailClient(results=[True])
    await handle_escalation(
        config=cfg_enabled, email_client=email_client, category=None, **base_kwargs
    )
    assert email_client.calls[0]["to"] == ["rishi@example.com", "anu@example.com"]
    assert "grievance" in email_client.calls[0]["subject"]


@pytest.mark.asyncio
async def test_category_grievance_routes_to_default_recipients(
    cfg_enabled, base_kwargs
):
    email_client = StubEmailClient(results=[True])
    await handle_escalation(
        config=cfg_enabled,
        email_client=email_client,
        category="grievance",
        **base_kwargs,
    )
    assert email_client.calls[0]["to"] == ["rishi@example.com", "anu@example.com"]


@pytest.mark.asyncio
async def test_category_docs_bc_routes_to_priti(cfg_enabled, base_kwargs):
    email_client = StubEmailClient(results=[True])
    await handle_escalation(
        config=cfg_enabled,
        email_client=email_client,
        category="docs_bc",
        **base_kwargs,
    )
    assert email_client.calls[0]["to"] == ["priti@example.com"]
    assert "docs_bc" in email_client.calls[0]["subject"]


@pytest.mark.asyncio
async def test_category_docs_midc_routes_to_dinesh(cfg_enabled, base_kwargs):
    email_client = StubEmailClient(results=[True])
    await handle_escalation(
        config=cfg_enabled,
        email_client=email_client,
        category="docs_midc",
        **base_kwargs,
    )
    assert email_client.calls[0]["to"] == ["dinesh@example.com"]
    assert "docs_midc" in email_client.calls[0]["subject"]


@pytest.mark.asyncio
async def test_category_docs_unknown_routes_to_both_office_recipients(
    cfg_enabled, base_kwargs
):
    email_client = StubEmailClient(results=[True])
    await handle_escalation(
        config=cfg_enabled,
        email_client=email_client,
        category="docs_unknown",
        **base_kwargs,
    )
    assert email_client.calls[0]["to"] == ["priti@example.com", "dinesh@example.com"]
    assert "docs_unknown" in email_client.calls[0]["subject"]


@pytest.mark.asyncio
async def test_unknown_category_falls_back_to_default(cfg_enabled, base_kwargs):
    """An unrecognised category string should NOT silently misroute — falls back to default."""
    email_client = StubEmailClient(results=[True])
    await handle_escalation(
        config=cfg_enabled,
        email_client=email_client,
        category="totally_made_up",
        **base_kwargs,
    )
    assert email_client.calls[0]["to"] == ["rishi@example.com", "anu@example.com"]


@pytest.mark.asyncio
async def test_docs_bc_skips_when_office_recipient_empty(base_kwargs):
    """If docs_bc category fires but priti's address isn't configured, fall back to default."""
    cfg = Config(
        gmail_client_id="x",
        gmail_client_secret="x",
        gmail_refresh_token="x",
        gmail_sender_email="x@example.com",
        escalation_recipients=("rishi@example.com",),
        escalation_recipients_docs_bc=(),  # not configured
        escalation_enabled=True,
    )
    email_client = StubEmailClient(results=[True])
    await handle_escalation(
        config=cfg, email_client=email_client, category="docs_bc", **base_kwargs
    )
    # Falls back to default — at least the user's email reaches someone
    assert email_client.calls[0]["to"] == ["rishi@example.com"]


# ── Category parsing (handler.parse_escalation_category) ─────────────


def test_parse_escalation_category_docs_bc():
    from bhai.escalations.handler import parse_escalation_category

    assert (
        parse_escalation_category(
            "Main Priti ko email kar rahi hoon.\nESCALATE: true\nESCALATE_CATEGORY: docs_bc"
        )
        == "docs_bc"
    )


def test_parse_escalation_category_case_insensitive():
    from bhai.escalations.handler import parse_escalation_category

    assert (
        parse_escalation_category("ESCALATE: TRUE\nescalate_category: DOCS_MIDC")
        == "docs_midc"
    )


def test_parse_escalation_category_unknown_returns_none():
    """A bad model output shouldn't silently misroute — fall back to None
    (handler treats None as 'grievance' default)."""
    from bhai.escalations.handler import parse_escalation_category

    assert (
        parse_escalation_category("ESCALATE: true\nESCALATE_CATEGORY: bogus_value")
        is None
    )


def test_parse_escalation_category_missing_returns_none():
    from bhai.escalations.handler import parse_escalation_category

    assert parse_escalation_category("ESCALATE: true") is None


def test_parse_escalation_category_empty_returns_none():
    from bhai.escalations.handler import parse_escalation_category

    assert parse_escalation_category("") is None
    assert parse_escalation_category(None) is None  # type: ignore[arg-type]


# ── work_location extraction + email body labelling ─────────────────


def test_extract_work_location_from_facts(store):
    """work_location: BC / MIDC in the facts list is picked up."""
    from bhai.escalations.handler import _extract_work_location

    store.save_memory(
        "tg_loc1",
        summary="some summary",
        facts=["name: Priya", "work_location: MIDC", "daughter age 8"],
    )
    assert _extract_work_location(store, "tg_loc1", "") == "MIDC"


def test_extract_work_location_case_insensitive(store):
    from bhai.escalations.handler import _extract_work_location

    store.save_memory(
        "tg_loc2",
        summary="",
        facts=["Work_Location: bc"],
    )
    assert _extract_work_location(store, "tg_loc2", "") == "BC"


def test_extract_work_location_from_profile_when_facts_silent(store):
    """If facts don't mention it but profile does, profile wins."""
    from bhai.escalations.handler import _extract_work_location

    store.save_memory("tg_loc3", summary="", facts=["just a name"])
    profile = "Priya, stitcher.\nwork_location: BC\n2 children."
    assert _extract_work_location(store, "tg_loc3", profile) == "BC"


def test_extract_work_location_returns_none_when_unknown(store):
    from bhai.escalations.handler import _extract_work_location

    assert _extract_work_location(store, "tg_never_saved", "") is None
    store.save_memory("tg_loc4", summary="", facts=["name: X"])
    assert _extract_work_location(store, "tg_loc4", "") is None


@pytest.mark.asyncio
async def test_email_body_includes_work_location_when_known(cfg_enabled, base_kwargs):
    """When work_location is in facts, the email body shows the office."""
    base_kwargs["store"].save_memory(
        base_kwargs["phone"],
        summary="",
        facts=["work_location: BC"],
    )
    email_client = StubEmailClient(results=[True])
    await handle_escalation(
        config=cfg_enabled, email_client=email_client, **base_kwargs
    )
    body = email_client.calls[0]["html_body"]
    assert "Work location" in body
    assert "BC office" in body
    # Subject is tagged too
    assert "/BC]" in email_client.calls[0]["subject"]


@pytest.mark.asyncio
async def test_email_body_flags_missing_work_location(cfg_enabled, base_kwargs):
    """When no work_location is known, the body explicitly flags it."""
    email_client = StubEmailClient(results=[True])
    await handle_escalation(
        config=cfg_enabled, email_client=email_client, **base_kwargs
    )
    body = email_client.calls[0]["html_body"]
    assert "UNKNOWN" in body
    assert "/LOC?]" in email_client.calls[0]["subject"]
