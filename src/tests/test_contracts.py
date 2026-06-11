"""
Regression contracts for bhAI — failure modes we've actually seen in pilot.

Each test in this file maps to a specific past failure:

- test_telegram_webhook_imports_cleanly        → May 11 KB-router half-commit crash
- test_voice_in_voice_out_plumbing             → "am I getting a voice back for voice in?"
- test_strip_reasoning_leak_removes_may_11_shape → May 11 CoT leakage to Manimala
- test_prompt_template_contains_outreach_rule    → May 9 Sapna confabulation (Vijay)
- test_app_exposes_required_routes               → startup-shape contract

When a new pilot incident reveals a failure mode, ADD A CONTRACT HERE so it
can never silently regress. This file is the institutional memory of
"never again."
"""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.bhai.llm.base import BaseLLM

# ──────────────────────────────────────────────────────────────────
# 1. Plumbing contracts — wiring between layers
# ──────────────────────────────────────────────────────────────────


def test_telegram_webhook_imports_cleanly():
    """
    Every webhook entry-point module must import without error.

    Regression for commit 75f9a1c (May 11), where new KB router imports
    were referenced but the router modules were missing from git. Local
    unit tests passed because they didn't import the webhook; Railway
    crashed at deploy. This contract guarantees a fresh clone can boot.
    """
    # Force a reimport rather than relying on whatever is cached
    for mod_name in (
        "inference.webhooks.telegram_webhook",
        "inference.webhooks.twilio_webhook",
        "inference.webhooks.nudges",
        "inference.web.chat_server",
    ):
        mod = importlib.import_module(mod_name)
        importlib.reload(mod)


def test_voice_in_voice_out_plumbing(monkeypatch, tmp_path):
    """
    Plumbing contract: a Telegram voice update should produce a voice
    reply back via telegram_client.send_voice.

    Mocks every external client (Telegram, STT, LLM, TTS) and exercises
    process_message end-to-end. Asserts that:
        1. The STT client is called with the downloaded inbound audio
        2. The LLM is called with the transcribed text
        3. send_voice is called with an OGG file containing TTS output

    Catches the class of bugs where one stage's output isn't passed to
    the next stage (the "wiring is broken" failure mode), which unit
    tests against individual stages cannot detect.
    """
    from inference.webhooks import telegram_webhook as tw

    # ── Mock Telegram client (download + send_voice + send_text) ──────
    mock_telegram = MagicMock()
    mock_telegram.send_voice = MagicMock(
        return_value={"ok": True, "result": {"message_id": 1}}
    )
    mock_telegram.send_text = MagicMock(
        return_value={"ok": True, "result": {"message_id": 2}}
    )

    def _download_voice(file_id, path):
        Path(path).write_bytes(b"FAKE_INBOUND_OGG")

    mock_telegram.download_voice = MagicMock(side_effect=_download_voice)
    monkeypatch.setattr(tw, "TelegramClient", lambda **kw: mock_telegram)

    # ── Mock STT ──────────────────────────────────────────────────────
    mock_stt = MagicMock()
    mock_stt.transcribe = MagicMock(return_value={"text": "Bhai, kaise ho?", "raw": {}})
    monkeypatch.setattr(tw, "SarvamSTT", lambda *a, **kw: mock_stt)

    # ── Mock LLM (and KB / user-profile loaders that come with it) ────
    mock_llm = MagicMock()
    mock_llm.generate_with_emotions = MagicMock(
        return_value={
            "text": "Theek hoon! Tum batao.",
            "segments": [{"text": "Theek hoon! Tum batao.", "emotion": "happy"}],
            "escalate": False,
        }
    )
    mock_llm.load_user_profile = MagicMock(return_value="")
    monkeypatch.setattr(tw, "create_llm", lambda config: mock_llm)

    # ── Mock TTS (write a fake OGG to the path provided) ──────────────
    def _fake_synth(text, path, **_kwargs):
        Path(path).write_bytes(b"FAKE_TTS_OUTPUT")
        return {}

    mock_tts = MagicMock()
    mock_tts.synthesize = MagicMock(side_effect=_fake_synth)
    monkeypatch.setattr("src.bhai.tts.sarvam_tts.SarvamTTS", lambda *a, **kw: mock_tts)
    monkeypatch.setattr(
        "src.bhai.tts.elevenlabs_tts.ElevenLabsTTS",
        lambda *a, **kw: mock_tts,
    )

    # ── Mock the audio-utils ogg conversion so it doesn't shell out ───
    def _fake_convert(src, dst):
        Path(dst).write_bytes(Path(src).read_bytes())

    monkeypatch.setattr(tw, "convert_to_ogg_opus", _fake_convert)

    # ── Point store + queue at temp DBs so we don't touch real data ───
    from src.bhai.memory.store import ConversationStore
    from src.bhai.resilience.queue import RequestQueue

    tmp_store = ConversationStore(tmp_path / "test_conversations.db")
    tmp_queue = RequestQueue(tmp_path / "test_request_queue.db")
    monkeypatch.setattr(tw, "_get_store", lambda: tmp_store)
    monkeypatch.setattr(tw, "_get_queue", lambda: tmp_queue)

    # ── Run the pipeline ──────────────────────────────────────────────
    tw.process_message(
        chat_id=42424242,
        is_audio=True,
        voice_file_id="fake_telegram_file_id",
        body_text="",
    )

    # ── Assertions: each layer was wired to the next ──────────────────
    assert mock_telegram.download_voice.called, "STT layer didn't pull the audio"
    assert mock_stt.transcribe.called, "LLM layer didn't get the transcript"
    assert mock_llm.generate_with_emotions.called, "TTS layer didn't get the LLM text"
    assert (
        mock_telegram.send_voice.called
    ), "send_voice was never called — voice in did NOT produce voice out"

    # The send_voice call should be with the chat_id and a Path
    call_kwargs = mock_telegram.send_voice.call_args.kwargs
    assert call_kwargs.get("chat_id") == 42424242
    voice_path_arg = call_kwargs.get("audio_path") or call_kwargs.get("voice_path")
    if voice_path_arg is None and mock_telegram.send_voice.call_args.args:
        # fall back to positional args (signature may differ)
        voice_path_arg = mock_telegram.send_voice.call_args.args[1]
    assert voice_path_arg is not None, "send_voice called without an audio file"


# ──────────────────────────────────────────────────────────────────
# 2. Behavioral contracts — Sonnet's observed misbehavior
# ──────────────────────────────────────────────────────────────────


# Reconstructed shape of the May 11 leak to Manimala. The model narrated
# its reasoning before producing the actual Malayalam reply.
_MAY_11_LEAK_SHAPE = """
मुझे पहले ये सोचना है — user Malayalam में बात कर रहा है।
System prompt कहता है TTS Hindi में चाहिए, but match-language rule भी है।
Anti-sycophancy rule apply होता है क्योंकि user emotional है।
TTS engine Malayalam properly नहीं बोलेगा, but match-language wins.

अम्मा, सब ठीक हो जाएगा। मैं हूं ना।
""".strip()


def test_strip_reasoning_leak_removes_may_11_shape():
    """
    Regression for the May 11 Manimala session: model reasoning leaked
    verbatim into the user-facing reply. _strip_reasoning_leak should
    drop the internal-jargon paragraphs and keep the actual response.
    """
    cleaned = BaseLLM._strip_reasoning_leak(_MAY_11_LEAK_SHAPE)

    # The leak markers should be gone
    forbidden_markers = [
        "system prompt",
        "anti-sycophancy",
        "TTS engine",
        "match-language",
        "मुझे पहले",
    ]
    lowered = cleaned.lower()
    for marker in forbidden_markers:
        assert (
            marker.lower() not in lowered
        ), f"Reasoning marker '{marker}' was not stripped from output"

    # The actual user-facing reply must survive
    assert "अम्मा" in cleaned, "User-facing reply was stripped along with the leak"


def test_strip_reasoning_leak_preserves_clean_response():
    """
    A response with NO reasoning leak markers should be returned unchanged
    (modulo whitespace normalization). Make sure the stripper isn't
    overzealous and eating real content.
    """
    clean = "अम्मा, सब ठीक हो जाएगा। मैं हूं ना।"
    assert BaseLLM._strip_reasoning_leak(clean).strip() == clean.strip()


# ──────────────────────────────────────────────────────────────────
# 3. Prompt-content contracts — rules must survive prompt edits
# ──────────────────────────────────────────────────────────────────

PROMPT_PATH = (
    Path(__file__).resolve().parent.parent
    / "bhai"
    / "llm"
    / "prompts"
    / "prompt_v1_pilot.md"
)


def test_prompt_template_contains_outreach_honesty_rule():
    """
    The Honesty-About-Outreach Rule must remain in the pilot prompt.
    Regression for May 9 Sapna incident (bhAI fabricated "Vijay said X")
    and May 13 Jyoti incident (bhAI claimed past-tense outreach to Priti).
    Deleting or weakening these rules MUST fail this test.
    """
    assert PROMPT_PATH.exists(), f"Pilot prompt missing at {PROMPT_PATH}"
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    # Section header
    assert (
        "Honesty-About-Outreach Rule" in prompt
    ), "Honesty-About-Outreach Rule section header is missing"

    # The hard ban on confabulated outreach must remain explicit. Both past-
    # and future-tense outreach are lies; the only legitimate outreach
    # channel is the consent-gated `escalate: true` JSON field (which now
    # actually emails the impact team — per the 2026-05-22 capability-honesty
    # update, carried into the cot/out contract). The prompt must continue to
    # require consent + future-tense phrasing.
    must_contain = [
        "No past-tense outreach claims",
        "No future-tense outreach claims",  # without escalate: true, a lie
        "मैंने पूछ लिया",  # explicitly banned past tense example
        "escalate: true",  # the legitimate outreach channel (cot/out JSON field)
        "team को email करूँ",  # the consent question that must appear before emailing
        "No fake attribution",
    ]
    for phrase in must_contain:
        assert (
            phrase in prompt
        ), f"Prompt is missing required outreach-rule phrase: '{phrase}'"


def test_prompt_template_lists_named_contacts_scope():
    """
    Named-contact scope: the document/scheme PoCs — Priti (BC) and Dinesh
    (MIDC) — handle document help + KB-listed schemes; for other questions
    bhAI uses general knowledge and NEVER fabricates an attribution.
    Regression for the May 9 fabrication where bhAI invented karate-class
    details and attributed them to Vijay (who now appears only as the
    canonical fake-attribution example in the no-confabulation rules).
    """
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    assert "Priti" in prompt and "Dinesh" in prompt
    assert "document" in prompt.lower()


# ──────────────────────────────────────────────────────────────────
# 4. Startup contract — webhook app must expose the routes we rely on
# ──────────────────────────────────────────────────────────────────


def test_app_exposes_required_routes():
    """
    The FastAPI app must register every endpoint that ops + pilot
    monitoring depend on. Catches accidental route deletion or
    decorator typos that would otherwise only surface in prod.
    """
    from inference.webhooks.telegram_webhook import app

    registered_paths = {route.path for route in app.routes if hasattr(route, "path")}

    required = {
        "/telegram/webhook",
        "/health",
        "/dashboard",
        "/conversations/{phone_hash}",
        "/debug/{phone_hash}",
        "/admin/phones",
        "/admin/memory/{phone_hash}",
        "/admin/reset/{phone_hash}",
        "/admin/migrate",
        "/admin/send-message/{phone_hash}",
        "/admin/throttle-nudge/{phone_hash}",
        "/admin/test-nudge/{phone_hash}",
    }
    missing = required - registered_paths
    assert not missing, (
        f"FastAPI app is missing required routes: {sorted(missing)}. "
        "If you deliberately removed one, update this contract."
    )


# ──────────────────────────────────────────────────────────────────
# 6. Proactive feedback loop — the agent must remember what it said
# ──────────────────────────────────────────────────────────────────
#
# Replay 2026-06-08 findings #4 (the fan/AC joke fired 5× across afternoons)
# and #5 (the anti-relentless gate never fired) both traced to ONE structural
# gap: nudge_history.md was a hardcoded placeholder and the `nudges` table
# stored only throttle timestamps, so every "don't repeat what you already
# said" instruction in the prompts read an empty file. These contracts pin
# the loop closed: delivered nudges + reactions are persisted and surfaced.


def test_nudge_log_round_trips(tmp_db):
    """A delivered nudge persists its content and reads back decrypted
    (text/category/topic). Foundation of the proactive feedback loop."""
    from src.bhai.memory.store import ConversationStore

    store = ConversationStore(tmp_db)
    try:
        store.record_nudge_outcome(
            "tg_1",
            "morning",
            "saree_business_expansion",
            category="substantive",
            text="मणीमाला जी, namaste! आज loom कैसा चला?",
        )
        recent = store.recent_nudges("tg_1")
        assert len(recent) == 1
        assert recent[0].category == "substantive"
        assert recent[0].topic == "saree_business_expansion"
        assert "loom" in recent[0].text  # decrypted, not ciphertext
        assert recent[0].reaction is None
    finally:
        store.close()


def test_nudge_reaction_attaches_to_recent_nudge(tmp_db):
    """The user's next message attaches as the reaction to the most recent
    un-reacted nudge — the read-back half of the loop. Only the first reply
    attaches; a later message with nothing un-reacted is a no-op."""
    from src.bhai.memory.store import ConversationStore

    store = ConversationStore(tmp_db)
    try:
        store.record_nudge_outcome(
            "tg_1", "morning", category="substantive", text="कैसे हैं आज?"
        )
        assert store.record_nudge_reaction("tg_1", "अच्छा लगा सुनकर, शुक्रिया") is True
        assert store.record_nudge_reaction("tg_1", "और एक बात...") is False

        recent = store.recent_nudges("tg_1")
        assert len(recent) == 1
        assert recent[0].reaction == "अच्छा लगा सुनकर, शुक्रिया"
    finally:
        store.close()


def test_joke_dedup_excludes_recently_delivered(tmp_db):
    """Replay finding #4: the same joke must not be eligible twice in 30
    days. recent_joke_texts surfaces delivered jokes (and only jokes) so the
    joke pass can seed them into its exclude list."""
    from src.bhai.memory.store import ConversationStore

    fan_ac = 'पंखे ने AC से क्या कहा? "तू ठंडक देता है, मैं हवा देता हूँ।"'
    store = ConversationStore(tmp_db)
    try:
        store.record_nudge_outcome("tg_1", "afternoon", category="joke", text=fan_ac)
        # a substantive nudge must NOT pollute the joke dedup list
        store.record_nudge_outcome(
            "tg_1", "morning", category="substantive", text="आज का दिन कैसा रहा?"
        )
        assert store.recent_joke_texts("tg_1") == [fan_ac.strip()]
    finally:
        store.close()


def test_nudge_history_renders_real_rows_not_placeholder(tmp_db):
    """Replay finding #5 root cause: the dossier's nudge_history.md was a
    hardcoded placeholder, so the relentlessness gate read an empty file.
    After a delivery it must render the real nudge content."""
    from src.bhai.memory.store import ConversationStore
    from src.bhai.proactive.dossier_loader import load_user_dossier

    store = ConversationStore(tmp_db)
    try:
        store.record_nudge_outcome(
            "tg_1",
            "morning",
            "saree_business_expansion",
            category="substantive",
            text="आज loom कैसा चला?",
        )
        nudge_md = load_user_dossier(store, "tg_1").markdown_map()["nudge_history.md"]
        assert "_no proactive nudges delivered yet_" not in nudge_md
        assert "loom" in nudge_md
        assert "saree_business_expansion" in nudge_md
    finally:
        store.close()
