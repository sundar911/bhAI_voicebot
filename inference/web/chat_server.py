"""
bhAI Dev Voice Chat — localhost web UI for testing the full voice pipeline.

Full loop: browser mic → STT → LLM → TTS → audio playback.
Reuses the same pipeline as the Twilio webhook.

Run:  uv run python inference/web/chat_server.py
Open: http://127.0.0.1:8002
"""

import logging
import sys
import uuid
from pathlib import Path
from urllib.parse import quote

from typing import List

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse

# ── Path setup (same pattern as twilio_webhook.py) ───────────────────
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bhai.audio_utils import ensure_dir, convert_to_ogg_opus
from src.bhai.config import load_config, DATA_DIR, KNOWLEDGE_BASE_DIR, INFERENCE_OUTPUTS_DIR
from src.bhai.llm import create_llm
from src.bhai.memory.store import ConversationStore
from src.bhai.memory.summarizer import (
    should_summarize,
    build_summarize_request,
    parse_summary,
    merge_facts,
)
from src.bhai.resilience.faq_cache import FAQCache
from src.bhai.stt.sarvam_stt import SarvamSTT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("bhai.web")

# ── Constants ────────────────────────────────────────────────────────
PHONE = "web_test_user"
PORT = 8002
HTML_PATH = Path(__file__).parent / "chat.html"
AUDIO_DIR = INFERENCE_OUTPUTS_DIR / "web_chat"

INTRO_MESSAGE = (
    "अरे हाय! मैं भाई हूँ — विधी की आवाज़ में बोलती हूँ पर विधी नहीं हूँ। "
    "मुझसे कुछ भी पूछो — मैं कहाँ रहती हूँ, मुझे किसने बनाया — "
    "और मैं भी आपके बारे में जानना चाहती हूँ! आपका नाम क्या है?"
)

# ── Lazy singletons ──────────────────────────────────────────────────
_config = None
_store = None
_faq_cache = None


def _get_config():
    global _config
    if _config is None:
        _config = load_config()
    return _config


def _get_store():
    global _store
    if _store is None:
        _store = ConversationStore(DATA_DIR / "conversations.db")
    return _store


def _get_faq_cache():
    global _faq_cache
    if _faq_cache is None:
        cfg = _get_config()
        _faq_cache = FAQCache(KNOWLEDGE_BASE_DIR, threshold=cfg.faq_cache_threshold)
    return _faq_cache


# ~15 Hindi chars/second speaking rate → 300 chars ≈ 20 seconds
MAX_TTS_CHARS = 300


def _split_for_tts(text: str) -> list:
    """Split text into TTS-safe chunks (≤ MAX_TTS_CHARS each) at sentence boundaries."""
    if len(text) <= MAX_TTS_CHARS:
        return [text]

    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= MAX_TTS_CHARS:
            chunks.append(remaining)
            break
        # Find last sentence boundary within limit
        window = remaining[:MAX_TTS_CHARS]
        cut = -1
        for sep in ["।", "!", "?", "\n"]:
            idx = window.rfind(sep)
            if idx > MAX_TTS_CHARS // 3:
                cut = max(cut, idx)
        if cut == -1:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = MAX_TTS_CHARS - 1
        chunks.append(remaining[: cut + 1].strip())
        remaining = remaining[cut + 1 :].strip()
    return chunks


def _synthesize_one(text: str, config) -> Path:
    """Synthesize a single TTS-safe chunk to audio."""
    ensure_dir(AUDIO_DIR)
    filename = f"{uuid.uuid4().hex[:12]}_response.ogg"
    output_path = AUDIO_DIR / filename

    if config.tts_backend == "elevenlabs":
        from src.bhai.tts.elevenlabs_tts import ElevenLabsTTS
        tts = ElevenLabsTTS(config)
        tts.synthesize(text, output_path)
    else:
        from src.bhai.tts.sarvam_tts import SarvamTTS
        tts = SarvamTTS(config)
        wav_path = AUDIO_DIR / f"{uuid.uuid4().hex[:12]}_raw.wav"
        tts.synthesize(text, wav_path)
        convert_to_ogg_opus(wav_path, output_path)
        wav_path.unlink(missing_ok=True)

    return output_path


def _synthesize(text: str, config) -> Path:
    """Split text into chunks, synthesize each, concatenate audio."""
    from pydub import AudioSegment

    chunks = _split_for_tts(text)
    if len(chunks) == 1:
        return _synthesize_one(chunks[0], config)

    # Synthesize each chunk and concatenate
    combined = AudioSegment.empty()
    temp_paths = []
    for chunk in chunks:
        path = _synthesize_one(chunk, config)
        temp_paths.append(path)
        combined += AudioSegment.from_ogg(str(path))

    # Export concatenated audio
    ensure_dir(AUDIO_DIR)
    output_path = AUDIO_DIR / f"{uuid.uuid4().hex[:12]}_combined.ogg"
    combined.export(str(output_path), format="ogg", codec="libopus")

    # Clean up temp files
    for p in temp_paths:
        p.unlink(missing_ok=True)

    logger.info("TTS: concatenated %d chunks into %s", len(chunks), output_path.name)
    return output_path


def _audio_response(audio_path: Path, **meta) -> FileResponse:
    """Return audio file with URL-encoded metadata headers (safe for non-ASCII)."""
    headers = {f"X-{k}": quote(str(v), safe="") for k, v in meta.items()}
    return FileResponse(audio_path, media_type="audio/ogg", headers=headers)


# ── FastAPI app ──────────────────────────────────────────────────────
app = FastAPI(title="bhAI Dev Voice Chat")


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error("Unhandled error: %s", exc)
    return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/")
def serve_ui():
    return FileResponse(HTML_PATH, media_type="text/html")


@app.get("/health")
def health():
    cfg = _get_config()
    return {"status": "healthy", "llm_backend": cfg.llm_backend, "tts_backend": cfg.tts_backend}


@app.post("/init")
def init_conversation():
    """Auto-called on page load when no history exists. Synthesizes bhAI's intro."""
    store = _get_store()
    config = _get_config()

    if not store.is_first_ever_message(PHONE):
        return JSONResponse({"reply": None, "already_started": True})

    session_id, _ = store.get_or_create_session(PHONE)
    store.save_message(PHONE, "assistant", INTRO_MESSAGE, session_id)

    # TTS for intro
    try:
        audio_path = _synthesize(INTRO_MESSAGE, config)
        logger.info("Sent intro voice message for web_test_user")
        return _audio_response(audio_path, Transcript=INTRO_MESSAGE, Source="intro")
    except Exception as e:
        logger.error("TTS failed for intro: %s", e)
        return JSONResponse({"reply": INTRO_MESSAGE, "source": "intro", "tts_failed": True})


@app.get("/history")
def get_history():
    """Return recent messages for restoring chat on page reload."""
    store = _get_store()
    messages = store.get_recent_messages(PHONE, limit=50)
    return {"messages": messages}


NUDGE_PROMPTS = [
    "अरे, सब ठीक है ना? मैं यहीं हूँ, बात करो!",
    "ओ भाई, कहाँ गए? मैं तो इंतज़ार कर रही हूँ!",
    "अरे, मुझे अकेला मत छोड़ो — कुछ तो बोलो!",
    "हेलो? मैं अभी भी यहाँ हूँ — बातें ख़त्म नहीं हुई!",
    "बोरियत हो रही है अकेले — कुछ मज़ेदार बताओ ना!",
]
_nudge_idx = 0


@app.post("/nudge")
def nudge():
    """Called by frontend after 60s silence. Sends a follow-up voice message."""
    global _nudge_idx
    config = _get_config()
    store = _get_store()

    nudge_text = NUDGE_PROMPTS[_nudge_idx % len(NUDGE_PROMPTS)]
    _nudge_idx += 1

    session_id, _ = store.get_or_create_session(PHONE)
    store.save_message(PHONE, "assistant", nudge_text, session_id)

    try:
        audio_path = _synthesize(nudge_text, config)
        return _audio_response(audio_path, Transcript=nudge_text, Source="nudge")
    except Exception as e:
        logger.error("Nudge TTS failed: %s", e)
        return JSONResponse({"reply": nudge_text, "source": "nudge"})


@app.post("/reset")
def reset_conversation():
    """Wipe test user's messages and memory for fresh prompt iteration."""
    store = _get_store()
    store._conn.execute("DELETE FROM messages WHERE phone = ?", (PHONE,))
    store._conn.execute("DELETE FROM memory WHERE phone = ?", (PHONE,))
    store._conn.commit()
    logger.info("Reset conversation for web_test_user")
    return {"status": "reset"}


@app.post("/chat")
def chat(audio: List[UploadFile] = File(...)):
    """
    Full voice pipeline: receive audio(s) → STT → LLM → TTS → return audio.
    Accepts multiple audio files (consecutive voice notes batched by frontend).
    """
    config = _get_config()
    store = _get_store()
    faq_cache = _get_faq_cache()

    # ── STT (transcribe all audio files, concatenate transcripts) ────
    ensure_dir(AUDIO_DIR)
    all_transcripts = []

    for audio_file in audio:
        run_id = uuid.uuid4().hex[:12]
        inbound_path = AUDIO_DIR / f"{run_id}_inbound.webm"

        try:
            with open(inbound_path, "wb") as f:
                f.write(audio_file.file.read())

            stt_work_dir = AUDIO_DIR / run_id
            ensure_dir(stt_work_dir)
            stt = SarvamSTT(config, work_dir=stt_work_dir)
            stt_result = stt.transcribe(inbound_path)
            text = stt_result["text"].strip()
            if text:
                all_transcripts.append(text)
                logger.info("STT transcript (%d/%d): %s", len(all_transcripts), len(audio), text)
        except Exception as e:
            logger.error("STT failed for %s: %s", audio_file.filename, e)

    transcript = " ".join(all_transcripts)
    if not transcript:
        return JSONResponse({"error": "Could not transcribe audio"}, status_code=400)

    if len(audio) > 1:
        logger.info("Combined %d voice notes: %s", len(audio), transcript[:100])

    # ── Session + save ───────────────────────────────────────────────
    session_id, is_new_session = store.get_or_create_session(PHONE)
    is_first_ever = store.is_first_ever_message(PHONE)
    store.save_message(PHONE, "user", transcript, session_id)

    # ── FAQ cache check ──────────────────────────────────────────────
    faq_match = faq_cache.match(transcript)
    if faq_match:
        response_text = faq_cache.format_response(faq_match)
        store.save_message(PHONE, "assistant", response_text, session_id)
        logger.info("FAQ hit: '%s'", faq_match.question)
        try:
            audio_path = _synthesize(response_text, config)
            return _audio_response(audio_path, Transcript=transcript, Reply=response_text, Source="faq")
        except Exception as e:
            logger.error("TTS failed: %s", e)
            return JSONResponse({"transcript": transcript, "reply": response_text, "source": "faq", "tts_failed": True})

    # ── LLM ──────────────────────────────────────────────────────────
    try:
        llm = create_llm(config)
        user_profile = llm.load_user_profile(PHONE)

        memory = store.get_memory(PHONE)
        memory_summary = ""
        extracted_facts = ""
        if memory:
            memory_summary = memory["summary"]
            if memory["facts"]:
                extracted_facts = "\n".join(f"- {f}" for f in memory["facts"])

        recent = store.get_recent_messages(PHONE, limit=8)

        llm_result = llm.generate(
            transcript,
            domain="hr_admin",
            user_profile=user_profile,
            memory_summary=memory_summary,
            extracted_facts=extracted_facts,
            conversation_history=recent,
            is_new_session=is_new_session,
        )
        response_text = llm_result["text"]
        escalate = llm_result["escalate"]

    except Exception as e:
        logger.error("LLM failed: %s", e)
        return JSONResponse({"error": f"LLM failed: {e}", "transcript": transcript}, status_code=500)

    # ── Save + summarize ─────────────────────────────────────────────
    store.save_message(PHONE, "assistant", response_text, session_id)
    _try_summarize(store, config, memory_summary, memory)

    # ── TTS ──────────────────────────────────────────────────────────
    try:
        audio_path = _synthesize(response_text, config)
        logger.info("Full pipeline done: STT→LLM→TTS, %d chars", len(response_text))
        return _audio_response(audio_path, Transcript=transcript, Reply=response_text, Escalate=str(escalate).lower(), Source="llm")
    except Exception as e:
        logger.error("TTS failed: %s", e)
        return JSONResponse({
            "transcript": transcript,
            "reply": response_text,
            "escalate": escalate,
            "source": "llm",
            "tts_failed": True,
        })


@app.post("/chat-text")
def chat_text(message: str = ""):
    """Text fallback — type a message, get voice back. For quick testing."""
    from pydantic import BaseModel
    from fastapi import Body

    # This is handled via query param or form field
    config = _get_config()
    store = _get_store()
    faq_cache = _get_faq_cache()

    if not message.strip():
        return JSONResponse({"error": "Empty message"}, status_code=400)

    transcript = message.strip()
    session_id, is_new_session = store.get_or_create_session(PHONE)
    is_first_ever = store.is_first_ever_message(PHONE)
    store.save_message(PHONE, "user", transcript, session_id)

    faq_match = faq_cache.match(transcript)
    if faq_match:
        response_text = faq_cache.format_response(faq_match)
        store.save_message(PHONE, "assistant", response_text, session_id)
        try:
            audio_path = _synthesize(response_text, config)
            return _audio_response(audio_path, Transcript=transcript, Reply=response_text, Source="faq")
        except Exception:
            return JSONResponse({"reply": response_text, "source": "faq", "tts_failed": True})

    try:
        llm = create_llm(config)
        user_profile = llm.load_user_profile(PHONE)
        memory = store.get_memory(PHONE)
        memory_summary = ""
        extracted_facts = ""
        if memory:
            memory_summary = memory["summary"]
            if memory["facts"]:
                extracted_facts = "\n".join(f"- {f}" for f in memory["facts"])
        recent = store.get_recent_messages(PHONE, limit=8)

        llm_result = llm.generate(
            transcript, domain="hr_admin", user_profile=user_profile,
            memory_summary=memory_summary, extracted_facts=extracted_facts,
            conversation_history=recent, is_new_session=is_new_session,
        )
        response_text = llm_result["text"]
        escalate = llm_result["escalate"]
    except Exception as e:
        return JSONResponse({"error": f"LLM failed: {e}"}, status_code=500)

    store.save_message(PHONE, "assistant", response_text, session_id)
    _try_summarize(store, config, memory_summary, memory)

    try:
        audio_path = _synthesize(response_text, config)
        return _audio_response(audio_path, Transcript=transcript, Reply=response_text, Escalate=str(escalate).lower(), Source="llm")
    except Exception:
        return JSONResponse({"reply": response_text, "escalate": escalate, "source": "llm", "tts_failed": True})


def _try_summarize(store, config, memory_summary="", memory=None):
    """Run summarization if due. Non-critical — failures logged only."""
    user_msg_count = store.count_user_messages(PHONE)
    if not should_summarize(user_msg_count):
        return
    try:
        llm = create_llm(config)
        recent_for_summary = store.get_recent_messages(PHONE, limit=10)
        summarize_prompt = build_summarize_request(memory_summary, recent_for_summary)
        summary_raw = llm._call_api_with_retry(
            "You are a conversation summarizer. Follow the instructions exactly.",
            summarize_prompt,
        )
        parsed = parse_summary(summary_raw)
        existing_facts = memory["facts"] if memory else []
        merged = merge_facts(existing_facts, parsed["facts"])
        store.save_memory(PHONE, parsed["summary"], merged)
        logger.info("Summarization complete, facts=%d", len(merged))
    except Exception as e:
        logger.error("Summarization failed: %s", e)


if __name__ == "__main__":
    import uvicorn

    print(f"\n  bhAI Dev Voice Chat → http://127.0.0.1:{PORT}\n")
    uvicorn.run(app, host="127.0.0.1", port=PORT)
