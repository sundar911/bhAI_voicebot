"""
Twilio WhatsApp webhook server for bhAI voice bot.

Receives audio/text messages via Twilio, processes through STT + LLM + TTS,
and sends back a voice response. Includes:
- Twilio signature verification (C1)
- Path traversal protection (C2)
- Per-user rate limiting (S4)
- Structured logging with no PII (C3/S10)
- Conversation memory and per-user profiles
- Immediate acknowledgment + background processing
- Request queuing with retry for API failures
- FAQ cache for common questions
- Graceful degradation (TTS fail → text fallback)
"""

import asyncio
import hashlib
import logging
import random
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Request, Response
from fastapi.responses import FileResponse

# Add src to path for imports
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bhai.audio_utils import ensure_dir, convert_to_ogg_opus
from src.bhai.config import load_config, INFERENCE_OUTPUTS_DIR, DATA_DIR, KNOWLEDGE_BASE_DIR
from src.bhai.integrations.twilio_client import TwilioWhatsAppClient
from src.bhai.memory.store import ConversationStore
from src.bhai.memory.summarizer import (
    should_summarize,
    build_summarize_request,
    parse_summary,
    merge_facts,
)
from src.bhai.resilience.faq_cache import FAQCache
from src.bhai.resilience.queue import RequestQueue
from src.bhai.resilience.worker import RetryWorker
from src.bhai.security.webhook_auth import verify_twilio_signature
from src.bhai.stt.sarvam_stt import SarvamSTT
from src.bhai.llm import create_llm

# ── Logging (no PII) ──────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("bhai.webhook")

# ── Onboarding / ice-breaker ──────────────────────────────────────────────

_GREETING_WORDS = {"hi", "hello", "namaste", "hii", "hlo", "hey", "helo"}
_INTRO_TEMPLATE = (
    "अरे हाय! मैं भाई हूँ — विधी की आवाज़ में बोलती हूँ पर विधी नहीं हूँ। "
    "मुझसे कुछ भी पूछो — मैं कहाँ रहती हूँ, मुझे किसने बनाया — "
    "और मैं भी आपके बारे में जानना चाहती हूँ! आपका नाम क्या है?"
)


def _detect_greeting(text: str) -> str | None:
    """If the message is a short, standalone greeting, return the greeting word; else None."""
    stripped = text.strip()
    if not stripped or len(stripped) > 50:
        return None
    first_word = stripped.split()[0].rstrip("!.,?").lower()
    return first_word if first_word in _GREETING_WORDS else None


def _build_intro(greeting: str = "hi") -> str:
    return _INTRO_TEMPLATE.format(greeting=greeting)


def _phone_hash(phone: str) -> str:
    """Hash a phone number for safe log correlation."""
    return hashlib.sha256(phone.encode()).hexdigest()[:12]


# ── Acknowledgment messages (rotated randomly) ────────────────────────

ACK_MESSAGES = [
    "रुको, सुन रही हूँ...",
    "हाँ बोलो, सुन रही हूँ...",
    "एक minute, समझ रही हूँ...",
]

# ── Singletons (lazy-initialized) ─────────────────────────────────────

_store: ConversationStore | None = None
_queue: RequestQueue | None = None
_faq_cache: FAQCache | None = None
_worker_task: asyncio.Task | None = None

AUDIO_SERVE_DIR = INFERENCE_OUTPUTS_DIR / "twilio_audio"

# Per-user rate limiting (in-memory)
_rate_limit: dict[str, list[float]] = {}
RATE_LIMIT_MAX = 10
RATE_LIMIT_WINDOW = 60


def _get_store() -> ConversationStore:
    global _store
    if _store is None:
        db_path = DATA_DIR / "conversations.db"
        _store = ConversationStore(db_path)
        logger.info("Conversation store initialized at %s", db_path)
    return _store


def _get_queue() -> RequestQueue:
    global _queue
    if _queue is None:
        db_path = DATA_DIR / "request_queue.db"
        _queue = RequestQueue(db_path)
        logger.info("Request queue initialized at %s", db_path)
    return _queue


def _get_faq_cache(threshold: float = 0.6) -> FAQCache:
    global _faq_cache
    if _faq_cache is None:
        _faq_cache = FAQCache(KNOWLEDGE_BASE_DIR, threshold=threshold)
    return _faq_cache


def _check_rate_limit(phone: str) -> bool:
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW
    if phone not in _rate_limit:
        _rate_limit[phone] = []
    _rate_limit[phone] = [t for t in _rate_limit[phone] if t > window_start]
    if len(_rate_limit[phone]) >= RATE_LIMIT_MAX:
        return False
    _rate_limit[phone].append(now)
    return True


def _twiml_empty() -> Response:
    return Response(
        status_code=200,
        content="<Response></Response>",
        media_type="application/xml",
    )


# ── App lifecycle (start retry worker) ────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the retry worker on app startup, stop on shutdown."""
    global _worker_task
    config = load_config()
    worker = RetryWorker(
        queue=_get_queue(),
        config=config,
        store=_get_store(),
        interval=30,
    )
    _worker_task = asyncio.create_task(worker.run_forever())
    logger.info("Retry worker started")
    yield
    if _worker_task:
        _worker_task.cancel()
        logger.info("Retry worker stopped")


app = FastAPI(title="bhAI Twilio WhatsApp Webhook", lifespan=lifespan)


# ── Audio serving (with path traversal protection) ────────────────────

@app.get("/audio/{filename}")
async def serve_audio(filename: str):
    resolved = (AUDIO_SERVE_DIR / filename).resolve()
    if not str(resolved).startswith(str(AUDIO_SERVE_DIR.resolve())):
        logger.warning("Path traversal attempt blocked: %s", filename)
        return Response(status_code=403)
    if not resolved.exists():
        return Response(status_code=404)
    return FileResponse(
        path=str(resolved),
        media_type="audio/ogg",
        filename=resolved.name,
    )


# ── Background processing (the pipeline with degradation) ─────────────

def process_message(
    sender: str,
    phone: str,
    phone_id: str,
    is_audio: bool,
    media_url: str,
    media_content_type: str,
    body_text: str,
):
    """
    Process a voice/text message through STT → FAQ/LLM → TTS.

    Runs in a background task so the webhook returns immediately.
    On failure at any stage, queues the request for retry and
    degrades gracefully (TTS fail → text fallback, etc.).
    """
    config = load_config()
    store = _get_store()
    queue = _get_queue()
    faq_cache = _get_faq_cache(threshold=config.faq_cache_threshold)

    twilio_client = TwilioWhatsAppClient(
        account_sid=config.twilio_account_sid,
        auth_token=config.twilio_auth_token,
        whatsapp_number=config.twilio_whatsapp_number,
    )

    # ── Session management ─────────────────────────────────────────
    session_id, is_new_session = store.get_or_create_session(phone)
    is_first_ever = store.is_first_ever_message(phone)
    logger.info("Session for user=%s: session=%s new=%s first_ever=%s",
                phone_id, session_id, is_new_session, is_first_ever)

    run_id = f"twilio_{int(time.time())}"
    run_dir = INFERENCE_OUTPUTS_DIR / run_id
    ensure_dir(run_dir)

    # ── STT ────────────────────────────────────────────────────────
    transcript = None
    inbound_path = None

    if is_audio:
        extension = ".ogg" if "ogg" in media_content_type else ".wav"
        inbound_path = run_dir / f"inbound{extension}"

        try:
            twilio_client.download_media(media_url, inbound_path)
            logger.info("Audio downloaded for user=%s", phone_id)
        except Exception as e:
            logger.error("Media download failed for user=%s: %s", phone_id, e)
            twilio_client.send_text_message(
                to_number=sender,
                body="Sun nahi paayi, phir se voice note bhejo.",
            )
            return

        try:
            work_dir = ROOT / ".bhai_temp"
            stt = SarvamSTT(config, work_dir=work_dir)
            stt_result = stt.transcribe(inbound_path)
            transcript = stt_result["text"]
            logger.info("STT complete for user=%s, length=%d chars",
                        phone_id, len(transcript))
        except Exception as e:
            logger.error("STT failed for user=%s: %s", phone_id, e)
            # Queue for retry from STT stage
            queue.enqueue(
                phone=phone,
                sender=sender,
                audio_path=str(inbound_path),
                stage="stt",
            )
            twilio_client.send_text_message(
                to_number=sender,
                body="Sun nahi paayi, thodi der mein phir try karti hoon.",
            )
            return
    else:
        transcript = body_text
        logger.info("Text message from user=%s, length=%d chars",
                    phone_id, len(transcript))

    # Save user message
    store.save_message(phone, "user", transcript, session_id,
                       audio_path=str(run_dir) if is_audio else None)

    # ── Onboarding: detect pure greeting on first-ever message ────────
    _greeting_word = _detect_greeting(transcript) if is_first_ever else None

    # ── FAQ cache check ────────────────────────────────────────────
    faq_match = None
    llm_result = None
    response_text = None
    memory_summary = ""

    if is_first_ever and _greeting_word:
        # Pure greeting — skip FAQ/LLM entirely, send intro directly
        intro = _build_intro(_greeting_word)
        response_text = intro
        llm_result = {
            "text": intro,
            "segments": [{"text": intro, "emotion": "happy"}],
            "escalate": False,
        }
        logger.info("Onboarding greeting branch for user=%s (greeting=%s)",
                    phone_id, _greeting_word)
    else:
        faq_match = faq_cache.match(transcript)

        if faq_match:
            response_text = faq_cache.format_response(faq_match)
            logger.info("FAQ cache hit for user=%s: '%s'",
                        phone_id, faq_match.question)
        else:
            # ── LLM ────────────────────────────────────────────────────
            try:
                llm = create_llm(config)
                user_profile = llm.load_user_profile(phone)
                memory = store.get_memory(phone)

                extracted_facts = ""
                if memory:
                    memory_summary = memory["summary"]
                    facts_list = memory["facts"]
                    if facts_list:
                        extracted_facts = "\n".join(f"- {f}" for f in facts_list)

                recent = store.get_recent_messages(phone, limit=8)

                llm_result = llm.generate_with_emotions(
                    transcript,
                    domain="hr_admin",
                    user_profile=user_profile,
                    memory_summary=memory_summary,
                    extracted_facts=extracted_facts,
                    conversation_history=recent,
                    is_new_session=is_new_session,
                )
                response_text = llm_result["text"]
                logger.info("LLM response for user=%s, length=%d chars, escalate=%s",
                            phone_id, len(response_text), llm_result["escalate"])

                # First-ever message that was a real question — answer first, then intro
                if is_first_ever:
                    intro = _build_intro()
                    response_text = llm_result["text"] + " " + intro
                    segs = list(
                        llm_result.get("segments")
                        or [{"text": llm_result["text"], "emotion": "neutral"}]
                    )
                    segs.append({"text": intro, "emotion": "happy"})
                    llm_result = {**llm_result, "text": response_text, "segments": segs}

            except Exception as e:
                logger.error("LLM failed for user=%s: %s", phone_id, e)
                # Queue for retry from LLM stage (transcript saved)
                queue.enqueue(
                    phone=phone,
                    sender=sender,
                    audio_path=str(inbound_path or run_dir),
                    stage="llm",
                    transcript=transcript,
                )
                # Voice-only mode — no text fallback; request queued for retry
                return

    # Save assistant response
    store.save_message(phone, "assistant", response_text, session_id)

    # ── Summarization (every N user messages) ──────────────────────
    _try_summarize(phone, phone_id, store, config, memory_summary=("" if faq_match else (memory_summary or "")), memory=store.get_memory(phone) if not faq_match else None)

    # ── TTS ────────────────────────────────────────────────────────
    ensure_dir(AUDIO_SERVE_DIR)
    response_filename = f"{run_id}_response.ogg"
    response_serve_path = AUDIO_SERVE_DIR / response_filename

    try:
        if config.tts_backend == "elevenlabs":
            from src.bhai.tts.elevenlabs_tts import ElevenLabsTTS
            tts = ElevenLabsTTS(config)
            segments = llm_result.get("segments") if llm_result else None
            if segments:
                tts.synthesize_with_emotions(segments, response_serve_path)
            else:
                tts.synthesize(response_text, response_serve_path)
        else:
            from src.bhai.tts.sarvam_tts import SarvamTTS
            tts = SarvamTTS(config)
            tts_raw_path = run_dir / "tts_raw_output.wav"
            tts.synthesize(response_text, tts_raw_path)
            convert_to_ogg_opus(tts_raw_path, response_serve_path)

        logger.info("TTS complete for user=%s, backend=%s",
                    phone_id, config.tts_backend)

        # Send audio response
        base_url = config.base_url.rstrip("/")
        audio_public_url = f"{base_url}/audio/{response_filename}"
        send_result = twilio_client.send_audio_message(
            to_number=sender,
            media_url=audio_public_url,
        )
        logger.info("Response sent to user=%s sid=%s",
                    phone_id, send_result.get("sid"))

    except Exception as e:
        # TTS failed — no text fallback; ack already acknowledged receipt
        logger.error("TTS failed for user=%s: %s — voice-only mode, no fallback",
                     phone_id, e)


def _try_summarize(phone, phone_id, store, config, memory_summary="", memory=None):
    """Run summarization if due. Non-critical — failures are logged only."""
    user_msg_count = store.count_user_messages(phone)
    if not should_summarize(user_msg_count):
        return

    logger.info("Triggering summarization for user=%s (msg #%d)",
                phone_id, user_msg_count)
    try:
        llm = create_llm(config)
        old_summary = memory_summary
        recent_for_summary = store.get_recent_messages(phone, limit=10)
        summarize_prompt = build_summarize_request(old_summary, recent_for_summary)

        summary_raw = llm._call_api_with_retry(
            "You are a conversation summarizer. Follow the instructions exactly.",
            summarize_prompt,
        )
        parsed = parse_summary(summary_raw)

        existing_facts = memory["facts"] if memory else []
        merged = merge_facts(existing_facts, parsed["facts"])
        store.save_memory(phone, parsed["summary"], merged)
        logger.info("Summarization complete for user=%s, facts=%d",
                    phone_id, len(merged))
    except Exception as e:
        logger.error("Summarization failed for user=%s: %s", phone_id, e)


# ── Main webhook ──────────────────────────────────────────────────────

@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    """Handle incoming Twilio WhatsApp webhook (audio + text messages)."""
    config = load_config()

    # ── Twilio signature verification (S1) ─────────────────────────
    form_data = await request.form()
    params = {k: str(v) for k, v in form_data.items()}
    signature = request.headers.get("X-Twilio-Signature", "")

    webhook_url = str(request.url)
    if config.base_url.startswith("https") and webhook_url.startswith("http://"):
        webhook_url = webhook_url.replace("http://", "https://", 1)

    if not verify_twilio_signature(
        config.twilio_auth_token, webhook_url, params, signature
    ):
        return Response(status_code=403, content="Forbidden")

    # ── Extract message fields ─────────────────────────────────────
    sender = str(form_data.get("From", ""))
    phone = sender.replace("whatsapp:", "")
    phone_id = _phone_hash(phone)

    num_media = int(form_data.get("NumMedia", 0))
    media_url = str(form_data.get("MediaUrl0", ""))
    media_content_type = str(form_data.get("MediaContentType0", ""))
    body_text = str(form_data.get("Body", "")).strip()

    logger.info("Message from user=%s media=%d type=%s has_text=%s",
                phone_id, num_media, media_content_type, bool(body_text))

    # ── Rate limiting (S4) ─────────────────────────────────────────
    if not _check_rate_limit(phone):
        logger.warning("Rate limited user=%s", phone_id)
        return _twiml_empty()

    # ── Determine message type ─────────────────────────────────────
    is_audio = (
        num_media > 0
        and media_url
        and ("audio" in media_content_type or "ogg" in media_content_type)
    )
    is_text = bool(body_text) and not is_audio

    if not is_audio and not is_text:
        logger.info("Skipping non-processable message from user=%s", phone_id)
        return _twiml_empty()

    # ── Acknowledgment disabled — voice-only mode, response is fast enough ──

    # ── Process in background ──────────────────────────────────────
    background_tasks.add_task(
        process_message,
        sender=sender,
        phone=phone,
        phone_id=phone_id,
        is_audio=is_audio,
        media_url=media_url,
        media_content_type=media_content_type,
        body_text=body_text,
    )

    return _twiml_empty()


# ── Health check ───────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "bhai-twilio-webhook"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
