"""
Telegram Bot webhook server for bhAI voice bot.

Receives voice/text messages via Telegram, processes through STT + LLM + TTS,
and sends back a voice response. Mirrors the Twilio webhook architecture but:
- No public BASE_URL needed — voice is uploaded directly via sendVoice
- No "join" sandbox flow — users tap t.me/<bot>
- Uses X-Telegram-Bot-Api-Secret-Token header instead of HMAC signatures
- Identifier format in DB: phone = f"tg_{chat_id}"
"""

import asyncio
import hashlib
import logging
import os as _os
import re
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import BackgroundTasks, FastAPI, Header, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

# Add src to path for imports
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Local imports — sit alongside this webhook
from inference.webhooks.nudges import nudge_loop  # noqa: E402
from src.bhai.audio_utils import convert_to_ogg_opus, ensure_dir
from src.bhai.config import (
    DATA_DIR,
    INFERENCE_OUTPUTS_DIR,
    KNOWLEDGE_BASE_DIR,
    load_config,
)
from src.bhai.escalations.handler import handle_escalation
from src.bhai.integrations.email_client import EmailClient
from src.bhai.integrations.telegram_client import TelegramClient
from src.bhai.llm import create_llm
from src.bhai.memory.store import ConversationStore
from src.bhai.memory.summarizer import merge_facts
from src.bhai.resilience.queue import RequestQueue
from src.bhai.resilience.worker import RetryWorker
from src.bhai.stt.sarvam_stt import SarvamSTT

# ── Logging (no PII) ──────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("bhai.telegram")

# ── Onboarding / ice-breaker ──────────────────────────────────────────────

_GREETING_WORDS = {"hi", "hello", "namaste", "hii", "hlo", "hey", "helo", "/start"}

# The Vidhi-voice clause only makes sense when ElevenLabs (Vidhi clone) is the
# TTS backend. With Sarvam (synthetic voice), it's a confusing claim — we'd be
# saying we sound like Vidhi when we don't. Conditionalised in `_build_intro`.
_INTRO_VIDHI_CLAUSE = "विधी की आवाज़ में बोलती हूँ पर विधी नहीं हूँ। "
_INTRO_OPENER = "अरे हाय! मैं भाई हूँ — "
_INTRO_BODY = (
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


def _build_intro(config) -> str:
    """Onboarding intro for first-ever messages. Drops the Vidhi-voice line on Sarvam."""
    if config.tts_backend == "elevenlabs":
        return _INTRO_OPENER + _INTRO_VIDHI_CLAUSE + _INTRO_BODY
    return _INTRO_OPENER + _INTRO_BODY


# Used when a user with prior conversation history (e.g. migrated from Twilio)
# sends /start on Telegram. The LLM uses memory + recent history to re-engage,
# rather than launching into a generic intro or treating it as a fresh greeting.
RE_ONBOARDING_INSTRUCTION = (
    "=== Re-onboarding Moment ===\n"
    "User has just sent /start. They are NOT new — you have prior conversation "
    "history with them (likely from WhatsApp/Twilio, now migrated to Telegram). "
    "Do all THREE of these in 1-2 short Devanagari sentences (≤ 280 chars total):\n"
    "1. ONE-line nod that you remember them — no full re-introduction needed. "
    'Use their name if you know it ("अरे [नाम]!" beats a generic hi).\n'
    "2. Reference ONE specific thing from your memory/recent history — a person "
    "they mentioned, a worry, a plan, a topic. Show you remember.\n"
    "3. ONE warm follow-up question rooted in that specific thing — not a "
    'generic "how are you".\n'
    "If memory/history is sparse, keep it short and warm — never make up details. "
    'No markdown. No bullets. No "how can I help you today" energy. '
    "Plain Devanagari sentences only.\n"
)


def _phone_hash(phone: str) -> str:
    """Hash an identifier for safe log correlation."""
    return hashlib.sha256(phone.encode()).hexdigest()[:12]


# ── TTS chunking (prevents ElevenLabs slow-mo on long Hindi text) ────
MAX_TTS_CHARS = 300


def _split_for_tts(text: str) -> list:
    """Split text into TTS-safe chunks at sentence boundaries."""
    if len(text) <= MAX_TTS_CHARS:
        return [text]
    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= MAX_TTS_CHARS:
            chunks.append(remaining)
            break
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


# ── Phone number extraction (send as text, not voice) ────────────────
_PHONE_RE = re.compile(r"(?:\+91[\s\-]?)?(\d[\d\s\-]{8,12}\d)")

_KNOWN_CONTACTS = {
    # Priti shifted from MIDC to BC (same phone number, new office assignment).
    # Dinesh now staffs MIDC docs but has no phone on file yet — no entry for
    # him here because the bot has no number to give the user. For MIDC docs
    # help the bot offers email escalation to Dinesh instead.
    "7738561086": "Priti (BC)",
    "7400426103": "Veena (MIDC – ESIC)",
    "9773964985": "Bharati (BC – ESIC)",
}


def _extract_phone_numbers(text: str):
    """Extract phone numbers from text, return (voice_text, text_message_or_None).

    Strips numbers from voice text so TTS doesn't mangle them.
    Returns a formatted text message with the numbers if any were found.
    """
    matches = _PHONE_RE.findall(text)
    numbers = []
    for m in matches:
        digits = re.sub(r"[\s\-]", "", m)
        if len(digits) == 10 and digits not in numbers:
            numbers.append(digits)

    if not numbers:
        return text, None

    voice_text = text
    for num in numbers:
        voice_text = re.sub(
            r"\+?91[\s\-]?"
            + re.escape(num)
            + r"|"
            + re.escape(num[:5])
            + r"[\s\-]?"
            + re.escape(num[5:])
            + r"|"
            + re.escape(num),
            "",
            voice_text,
        )
    voice_text = re.sub(r"\s*[–\-]\s*(?=[,।\.\s]|$)", "", voice_text)
    voice_text = re.sub(r"\s{2,}", " ", voice_text).strip()

    lines = ["📞 Contact:"]
    for num in numbers:
        label = _KNOWN_CONTACTS.get(num, "")
        if label:
            lines.append(f"{label} – {num}")
        else:
            lines.append(num)
    text_msg = "\n".join(lines)

    return voice_text, text_msg


_MAP_RE = re.compile(r"<map>(.*?)</map>", re.DOTALL | re.IGNORECASE)


def _extract_map_links(text: str):
    """Extract ``<map>place</map>`` blocks → (voice_text with the blocks
    removed, a follow-up text message with tappable Google Maps links or None).

    The bot says the place name naturally in the voice AND wraps it in a
    ``<map>…</map>`` block; we strip the block from the spoken copy and send a
    one-tap Maps link as a separate text, so she can open the location instead
    of typing it into Maps. Mirrors the phone-number pipeline.
    """
    import urllib.parse

    places = [m.strip() for m in _MAP_RE.findall(text) if m.strip()]
    if not places:
        return text, None

    voice_text = _MAP_RE.sub("", text)
    voice_text = re.sub(r"\s{2,}", " ", voice_text).strip()

    parts, seen = [], set()
    for place in places:
        if place in seen:
            continue
        seen.add(place)
        url = (
            "https://www.google.com/maps/search/?api=1&query="
            + urllib.parse.quote_plus(place)
        )
        parts.append(f"📍 {place}\n{url}")
    return voice_text, "\n\n".join(parts) if parts else None


_IMAGE_RE = re.compile(r"<image>(.*?)</image>", re.DOTALL | re.IGNORECASE)


def _extract_image_brief(text: str):
    """Extract a single ``<image>brief</image>`` block → (voice_text with the
    block removed, the image brief, or None).

    The reactive bot emits this block when the user asks it to MAKE an image
    (a poster, a card, a logo). The webhook generates it via nanobanana and
    sends it as a photo after the voice note. The brief is the model's
    PII-free visual description; the block is silent (stripped before TTS).
    """
    m = _IMAGE_RE.search(text)
    if not m:
        return text, None
    brief = m.group(1).strip()
    voice_text = _IMAGE_RE.sub("", text)
    voice_text = re.sub(r"\s{2,}", " ", voice_text).strip()
    return voice_text, (brief or None)


# ── Singletons (lazy-initialized) ─────────────────────────────────────

_store: ConversationStore | None = None
_queue: RequestQueue | None = None
_email_client: EmailClient | None = None
_worker_task: asyncio.Task | None = None
# Captured at app startup so sync background tasks (process_message) can
# schedule coroutines (handle_escalation) back onto the main event loop via
# asyncio.run_coroutine_threadsafe. FastAPI runs sync BackgroundTasks in a
# threadpool — there's no running loop to call asyncio.create_task on.
_main_event_loop: asyncio.AbstractEventLoop | None = None

AUDIO_RESPONSE_DIR = INFERENCE_OUTPUTS_DIR / "telegram_audio"

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


def _get_email_client(config) -> EmailClient | None:
    """Lazy-init the Gmail API email client.

    Returns None when any of the four OAuth values is unset — the
    escalation handler short-circuits on a None/disabled client so dev
    runs are safe.
    """
    global _email_client
    if not (
        config.gmail_client_id
        and config.gmail_client_secret
        and config.gmail_refresh_token
        and config.gmail_sender_email
    ):
        return None
    if _email_client is None:
        _email_client = EmailClient(
            client_id=config.gmail_client_id,
            client_secret=config.gmail_client_secret,
            refresh_token=config.gmail_refresh_token,
            sender_email=config.gmail_sender_email,
        )
        logger.info(
            "Email client initialized (backend=gmail-api, sender=%s, recipients=%d)",
            config.gmail_sender_email,
            len(config.escalation_recipients),
        )
    return _email_client


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


# ── App lifecycle (start retry worker) ────────────────────────────────


_nudge_task: asyncio.Task | None = None
_webhook_watchdog_task: asyncio.Task | None = None

# Module-level state for the watchdog backoff. After 3 consecutive setWebhook
# failures, we stop trying for 1 hour to avoid hammering the Telegram API.
_webhook_register_failures = 0
_webhook_backoff_until: float = 0.0
_WEBHOOK_MAX_FAILURES = 3
_WEBHOOK_BACKOFF_SECONDS = 3600


def _resolve_public_url(config) -> str | None:
    """Pick the public URL the webhook should be reachable at.

    Resolution order:
    1. WEBHOOK_PUBLIC_URL — explicit override (custom domain, ngrok, etc.)
    2. RAILWAY_PUBLIC_DOMAIN — Railway auto-injects this; use https:// scheme
    3. None — caller should skip auto-heal
    """
    if config.webhook_public_url:
        return config.webhook_public_url.rstrip("/")
    if config.railway_public_domain:
        domain = (
            config.railway_public_domain.strip().lstrip("https://").lstrip("http://")
        )
        return f"https://{domain}".rstrip("/")
    return None


def _ensure_webhook_registered(
    client: TelegramClient,
    expected_url: str,
    secret_token: str | None,
) -> bool:
    """Make sure Telegram is pointing its webhook at us. Returns True if a
    re-registration was performed (or attempted), False if no action was needed.

    Backs off after consecutive failures so we don't flood the Telegram API
    when their service is having a bad day.
    """
    global _webhook_register_failures, _webhook_backoff_until

    now = time.time()
    if now < _webhook_backoff_until:
        return False  # in backoff window, skip silently

    try:
        info = client.get_webhook_info()
    except Exception as e:
        logger.warning("Webhook watchdog: getWebhookInfo failed: %s", e)
        return False

    result = info.get("result", {}) if isinstance(info, dict) else {}
    current_url = result.get("url", "")
    last_error = result.get("last_error_message")

    if current_url == expected_url and not last_error:
        return False  # already correct

    logger.warning(
        "Webhook drift detected — was=%r expected=%r last_error=%r — re-registering",
        current_url,
        expected_url,
        last_error,
    )
    try:
        client.set_webhook(
            url=expected_url,
            secret_token=secret_token or None,
            allowed_updates=["message", "edited_message"],
        )
    except Exception as e:
        _webhook_register_failures += 1
        logger.error(
            "Webhook setWebhook failed (%d/%d): %s",
            _webhook_register_failures,
            _WEBHOOK_MAX_FAILURES,
            e,
        )
        if _webhook_register_failures >= _WEBHOOK_MAX_FAILURES:
            _webhook_backoff_until = now + _WEBHOOK_BACKOFF_SECONDS
            logger.error(
                "Webhook watchdog: %d consecutive failures, backing off for %ds",
                _webhook_register_failures,
                _WEBHOOK_BACKOFF_SECONDS,
            )
        return True  # we tried

    _webhook_register_failures = 0
    logger.warning(
        "Webhook re-registered: %s (secret=%s)",
        expected_url,
        "set" if secret_token else "(none)",
    )
    return True


async def _webhook_watchdog_loop(config) -> None:
    """Periodically verify the webhook is still pointed at us; re-register if not.

    Runs `_ensure_webhook_registered` every `webhook_watchdog_interval_seconds`
    in a thread executor so the blocking HTTP calls don't stall the event loop.
    """
    expected_base = _resolve_public_url(config)
    if not expected_base:
        logger.warning(
            "Webhook watchdog: neither WEBHOOK_PUBLIC_URL nor "
            "RAILWAY_PUBLIC_DOMAIN set — auto-heal disabled."
        )
        return
    if not config.telegram_bot_token:
        logger.warning("Webhook watchdog: TELEGRAM_BOT_TOKEN missing — disabled.")
        return

    expected_url = f"{expected_base}/telegram/webhook"
    interval = max(60, config.webhook_watchdog_interval_seconds)
    logger.info(
        "Webhook watchdog starting (target=%s, interval=%ds)",
        expected_url,
        interval,
    )

    client = TelegramClient(bot_token=config.telegram_bot_token)
    loop = asyncio.get_running_loop()
    while True:
        try:
            await loop.run_in_executor(
                None,
                _ensure_webhook_registered,
                client,
                expected_url,
                config.telegram_webhook_secret,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Webhook watchdog tick failed: %s", e)
        await asyncio.sleep(interval)


def _send_nudge(
    chat_id: int,
    slot: str,
    text: str,
    text_artifact: Optional[str] = None,
    artifact_path: Optional[Path] = None,
) -> None:
    """Deliver a generated nudge as a Telegram voice message and log it.

    Used as the `send_fn` callback for the nudge loop. Persists the nudge
    text to the conversation store as an assistant message so it shows up
    in /conversations and the LLM sees it in subsequent context. When the v2
    thinker produced a paste-able ``text_artifact`` (a catalog / list /
    template), it rides as a SEPARATE text message after the voice note — the
    voice note describes it; TTS never speaks its formatting.
    """
    config = load_config()
    store = _get_store()
    phone = f"tg_{chat_id}"
    phone_id = _phone_hash(phone)

    session_id, _ = store.get_or_create_session(phone)
    store.save_message(phone, "assistant", text, session_id)

    run_id = f"nudge_{slot}_{int(time.time())}_{chat_id}"
    run_dir = INFERENCE_OUTPUTS_DIR / run_id
    telegram_client = TelegramClient(bot_token=config.telegram_bot_token)

    _synthesize_and_send_voice(
        telegram_client=telegram_client,
        chat_id=chat_id,
        text=text,
        config=config,
        run_id=run_id,
        run_dir=run_dir,
        phone_id=phone_id,
    )

    if artifact_path:
        try:
            telegram_client.send_photo(chat_id=chat_id, image_path=artifact_path)
            logger.info("Nudge image sent to user=%s", phone_id)
        except Exception as e:
            logger.error("Nudge image failed for user=%s: %s", phone_id, e)

    if text_artifact:
        try:
            telegram_client.send_text(chat_id=chat_id, body=text_artifact)
            store.save_message(phone, "assistant", text_artifact, session_id)
            logger.info("Nudge text artifact sent to user=%s", phone_id)
        except Exception as e:
            logger.error("Nudge text artifact failed for user=%s: %s", phone_id, e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the retry worker + nudge loop + webhook watchdog on app startup."""
    global _worker_task, _nudge_task, _webhook_watchdog_task, _main_event_loop
    _main_event_loop = asyncio.get_running_loop()
    config = load_config()
    worker = RetryWorker(
        queue=_get_queue(),
        config=config,
        store=_get_store(),
        interval=30,
    )
    _worker_task = asyncio.create_task(worker.run_forever())
    logger.info("Retry worker started")

    _nudge_task = asyncio.create_task(
        nudge_loop(
            config=config,
            store=_get_store(),
            send_fn=_send_nudge,
            phone_hash_fn=_phone_hash,
        )
    )

    # Verify Telegram bot token at startup (best-effort)
    if config.telegram_bot_token:
        try:
            client = TelegramClient(config.telegram_bot_token)
            me = client.get_me()
            if me.get("ok"):
                bot = me.get("result", {})
                logger.info(
                    "Telegram bot ready: @%s (%s)",
                    bot.get("username"),
                    bot.get("first_name"),
                )
            else:
                logger.warning("Telegram getMe returned: %s", me)

            # Self-heal the webhook on every startup. Closes the gap left by
            # any stale --delete or polling experiment that cleared the URL.
            expected_base = _resolve_public_url(config)
            if expected_base:
                _ensure_webhook_registered(
                    client,
                    expected_url=f"{expected_base}/telegram/webhook",
                    secret_token=config.telegram_webhook_secret,
                )
        except Exception as e:
            logger.warning("Telegram getMe / webhook check failed: %s", e)
    else:
        logger.warning("TELEGRAM_BOT_TOKEN not set — webhook will not work")

    _webhook_watchdog_task = asyncio.create_task(_webhook_watchdog_loop(config))

    yield
    if _worker_task:
        _worker_task.cancel()
        logger.info("Retry worker stopped")
    if _nudge_task:
        _nudge_task.cancel()
        logger.info("Nudge loop stopped")
    if _webhook_watchdog_task:
        _webhook_watchdog_task.cancel()
        logger.info("Webhook watchdog stopped")


app = FastAPI(title="bhAI Telegram Webhook", lifespan=lifespan)


# ── Background processing (the pipeline with degradation) ─────────────


def process_message(
    chat_id: int,
    is_audio: bool,
    voice_file_id: str,
    body_text: str,
):
    """
    Process a voice/text message from Telegram through STT → FAQ/LLM → TTS.

    Runs in a background task so the webhook returns immediately.
    On failure at any stage, queues the request for retry and
    degrades gracefully.
    """
    config = load_config()
    store = _get_store()
    queue = _get_queue()

    telegram_client = TelegramClient(bot_token=config.telegram_bot_token)

    # Use chat_id as the per-user identifier with a `tg_` prefix to avoid
    # collisions with Twilio phone numbers in the same DB.
    phone = f"tg_{chat_id}"
    phone_id = _phone_hash(phone)

    # ── Session management ─────────────────────────────────────────
    session_id, is_new_session = store.get_or_create_session(phone)
    is_first_ever = store.is_first_ever_message(phone)
    logger.info(
        "Session for user=%s: session=%s new=%s first_ever=%s",
        phone_id,
        session_id,
        is_new_session,
        is_first_ever,
    )

    run_id = f"telegram_{int(time.time())}_{chat_id}"
    run_dir = INFERENCE_OUTPUTS_DIR / run_id
    ensure_dir(run_dir)

    # ── STT ────────────────────────────────────────────────────────
    transcript: str | None = None
    inbound_path: Path | None = None

    if is_audio:
        inbound_path = run_dir / "inbound.ogg"

        try:
            telegram_client.download_voice(voice_file_id, inbound_path)
            logger.info("Voice downloaded for user=%s", phone_id)
        except Exception as e:
            logger.error("Voice download failed for user=%s: %s", phone_id, e)
            try:
                telegram_client.send_text(
                    chat_id=chat_id,
                    body="Sun nahi paayi, phir se voice note bhejo.",
                )
            except Exception:
                pass
            return

        try:
            work_dir = ROOT / ".bhai_temp"
            stt = SarvamSTT(config, work_dir=work_dir)
            stt_result = stt.transcribe(inbound_path)
            transcript = stt_result["text"]
            logger.info(
                "STT complete for user=%s, length=%d chars", phone_id, len(transcript)
            )
        except Exception as e:
            logger.error("STT failed for user=%s: %s", phone_id, e)
            queue.enqueue(
                phone=phone,
                sender=str(chat_id),
                audio_path=str(inbound_path),
                stage="stt",
            )
            try:
                telegram_client.send_text(
                    chat_id=chat_id,
                    body="Sun nahi paayi, thodi der mein phir try karti hoon.",
                )
            except Exception:
                pass
            return
    else:
        transcript = body_text
        logger.info(
            "Text message from user=%s, length=%d chars", phone_id, len(transcript)
        )

    # Save user message
    store.save_message(
        phone,
        "user",
        transcript,
        session_id,
        audio_path=str(run_dir) if is_audio else None,
    )

    # Proactive feedback loop: if this message is the user's first reply
    # within 24h of a delivered nudge, attach it as that nudge's reaction so
    # the next thinking pass can learn what landed (no-op if no recent nudge).
    store.record_nudge_reaction(phone, transcript)

    # ── Onboarding: detect greetings (always — /start can re-onboard returning users) ──
    _greeting_word = _detect_greeting(transcript)
    is_re_onboarding = (not is_first_ever) and _greeting_word == "/start"

    # ── LLM call (FAQ short-circuit dropped — every reply runs through Sonnet
    # so output is always in bhAI's voice / Hindi, not raw .md content). ──
    llm_result = None
    response_text = None
    memory_summary = ""
    memory: Optional[Dict[str, Any]] = None  # set inside the LLM branch
    user_profile = ""  # set inside the LLM branch; default for greeting branch

    if is_first_ever and _greeting_word:
        intro = _build_intro(config)
        response_text = intro
        llm_result = {
            "text": intro,
            "segments": [{"text": intro, "emotion": "happy"}],
            "escalate": False,
        }
        logger.info(
            "Onboarding greeting branch for user=%s (greeting=%s)",
            phone_id,
            _greeting_word,
        )
    else:
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

            mode_instruction = RE_ONBOARDING_INSTRUCTION if is_re_onboarding else ""
            if is_re_onboarding:
                logger.info("Re-onboarding branch for user=%s on /start", phone_id)

            llm_result = llm.generate_with_emotions(
                transcript,
                domain="hr_admin",
                user_profile=user_profile,
                memory_summary=memory_summary,
                extracted_facts=extracted_facts,
                conversation_history=recent,
                is_new_session=is_new_session or is_re_onboarding,
                mode_instruction=mode_instruction,
            )
            response_text = llm_result["text"]
            logger.info(
                "LLM response for user=%s, length=%d chars, escalate=%s",
                phone_id,
                len(response_text),
                llm_result["escalate"],
            )

            if is_first_ever:
                intro = _build_intro(config)
                response_text = llm_result["text"] + " " + intro
                segs = list(
                    llm_result.get("segments")
                    or [{"text": llm_result["text"], "emotion": "neutral"}]
                )
                segs.append({"text": intro, "emotion": "happy"})
                llm_result = {**llm_result, "text": response_text, "segments": segs}

        except Exception as e:
            logger.error("LLM failed for user=%s: %s", phone_id, e)
            queue.enqueue(
                phone=phone,
                sender=str(chat_id),
                audio_path=str(inbound_path or run_dir),
                stage="llm",
                transcript=transcript,
            )
            return

    # Save assistant response
    store.save_message(phone, "assistant", response_text, session_id)

    # ── Memory patches (Letta-style self-edited core memory) ──────
    # The LLM emits zero or more `<memory>` blocks per turn (see
    # MEMORY_INSTRUCTION in src/bhai/llm/base.py). The blocks are already
    # stripped from response_text before TTS; here we just persist the
    # parsed deltas into the store.
    #
    # Replaces the legacy every-5-turns _try_summarize() flow. The
    # summariser code in src/bhai/memory/summarizer.py is kept as a
    # legacy fallback but no longer called from the hot path.
    _apply_memory_patches(
        phone=phone,
        phone_id=phone_id,
        store=store,
        memory_patches=(llm_result or {}).get("memory_patches"),
        prior_memory=memory,
    )

    _synthesize_and_send_voice(
        telegram_client=telegram_client,
        chat_id=chat_id,
        text=response_text,
        config=config,
        run_id=run_id,
        run_dir=run_dir,
        phone_id=phone_id,
    )
    # Phone-number text dispatch is handled inside _synthesize_and_send_voice
    # via _extract_phone_numbers (added 2026-04-28 in commit 48b6233c). The
    # extractor strips digits from voice_text AND sends a labelled
    # Telegram text message ("📞 Contact: Priti (BC) – 7738561086") when
    # numbers are present in the LLM reply.

    # ── Escalation: send email to impact team + follow-up confirmation ──
    # Scheduled AFTER the promise voice note above so the user always hears
    # "main email karne wali hoon" before the system-generated confirmation
    # ("kar diya" / "nahi ja paaya") arrives.
    if llm_result and llm_result.get("escalate"):
        _schedule_escalation(
            config=config,
            store=store,
            telegram_client=telegram_client,
            phone=phone,
            chat_id=chat_id,
            phone_id=phone_id,
            session_id=session_id,
            transcript=transcript,
            response_text=response_text,
            user_profile=user_profile,
            run_id=run_id,
            run_dir=run_dir,
            category=llm_result.get("category"),
        )


def _schedule_escalation(
    *,
    config,
    store: ConversationStore,
    telegram_client: TelegramClient,
    phone: str,
    chat_id: int,
    phone_id: str,
    session_id: str,
    transcript: str,
    response_text: str,
    user_profile: str,
    run_id: str,
    run_dir: Path,
    category: str | None = None,
) -> None:
    """Schedule handle_escalation onto the main event loop.

    process_message runs in a FastAPI threadpool worker (sync `def`), so we
    can't asyncio.create_task here — no running loop in this thread. We use
    run_coroutine_threadsafe against the loop captured in lifespan().
    """
    email_client = _get_email_client(config)
    if email_client is None:
        logger.warning(
            "Escalation triggered for user=%s but Gmail OAuth credentials "
            "are unset (GMAIL_CLIENT_ID/CLIENT_SECRET/REFRESH_TOKEN/SENDER_EMAIL) "
            "— no email will be sent",
            phone_id,
        )
        return

    if _main_event_loop is None:
        logger.error(
            "Escalation triggered for user=%s but main event loop not "
            "captured (lifespan didn't run) — dropping",
            phone_id,
        )
        return

    asyncio.run_coroutine_threadsafe(
        handle_escalation(
            config=config,
            email_client=email_client,
            store=store,
            voice_sender=_synthesize_and_send_voice,
            phone=phone,
            chat_id=chat_id,
            phone_id=phone_id,
            session_id=session_id,
            user_transcript=transcript,
            bot_response=response_text,
            recent_messages=store.get_recent_messages(phone, limit=8),
            user_profile=user_profile,
            run_id=run_id,
            run_dir=run_dir,
            telegram_client=telegram_client,
            category=category,
        ),
        _main_event_loop,
    )


def _synthesize_and_send_voice(
    *,
    telegram_client: TelegramClient,
    chat_id: int,
    text: str,
    config,
    run_id: str,
    run_dir: Path,
    phone_id: str,
) -> bool:
    """Run text through TTS chunking + synthesis and send the OGG to Telegram.

    Phone numbers are stripped from the voice copy and sent as a follow-up
    text message instead, so TTS doesn't mangle digits.

    Returns True on success, False on failure (failure is logged, not raised).
    """
    voice_text, contact_text_msg = _extract_phone_numbers(text)
    voice_text, map_text_msg = _extract_map_links(voice_text)
    voice_text, image_brief = _extract_image_brief(voice_text)

    ensure_dir(AUDIO_RESPONSE_DIR)
    ensure_dir(run_dir)
    response_path = AUDIO_RESPONSE_DIR / f"{run_id}_response.ogg"

    try:
        chunks = _split_for_tts(voice_text)

        if len(chunks) == 1:
            if config.tts_backend == "elevenlabs":
                from src.bhai.tts.elevenlabs_tts import ElevenLabsTTS

                tts = ElevenLabsTTS(config)
                tts.synthesize(chunks[0], response_path)
            else:
                from src.bhai.tts.sarvam_tts import SarvamTTS

                tts = SarvamTTS(config)
                tts_raw_path = run_dir / "tts_raw_output.wav"
                tts.synthesize(chunks[0], tts_raw_path)
                convert_to_ogg_opus(tts_raw_path, response_path)
        else:
            from pydub import AudioSegment as PydubSegment

            combined = PydubSegment.empty()
            for i, chunk in enumerate(chunks):
                chunk_path = AUDIO_RESPONSE_DIR / f"{run_id}_chunk{i}.ogg"
                if config.tts_backend == "elevenlabs":
                    from src.bhai.tts.elevenlabs_tts import ElevenLabsTTS

                    tts = ElevenLabsTTS(config)
                    tts.synthesize(chunk, chunk_path)
                else:
                    from src.bhai.tts.sarvam_tts import SarvamTTS

                    tts = SarvamTTS(config)
                    tts_raw = run_dir / f"tts_chunk{i}_raw.wav"
                    tts.synthesize(chunk, tts_raw)
                    convert_to_ogg_opus(tts_raw, chunk_path)
                combined += PydubSegment.from_ogg(str(chunk_path))
                chunk_path.unlink(missing_ok=True)
            combined.export(str(response_path), format="ogg", codec="libopus")
            logger.info(
                "TTS: concatenated %d chunks for user=%s", len(chunks), phone_id
            )

        logger.info(
            "TTS complete for user=%s, backend=%s", phone_id, config.tts_backend
        )

        send_result = telegram_client.send_voice(
            chat_id=chat_id, audio_path=response_path
        )
        logger.info(
            "Voice sent to user=%s message_id=%s",
            phone_id,
            send_result.get("message_id"),
        )

        if contact_text_msg:
            try:
                telegram_client.send_text(chat_id=chat_id, body=contact_text_msg)
                logger.info("Contact text sent to user=%s", phone_id)
            except Exception as text_err:
                logger.error("Contact text failed for user=%s: %s", phone_id, text_err)

        if map_text_msg:
            try:
                telegram_client.send_text(chat_id=chat_id, body=map_text_msg)
                logger.info("Map link text sent to user=%s", phone_id)
            except Exception as map_err:
                logger.error("Map link text failed for user=%s: %s", phone_id, map_err)

        # The bot asked to MAKE an image (poster/card/logo) — generate it via
        # nanobanana (scrub-gated inside generate_image) and send as a photo
        # after the voice. Failure is logged, never raised — the voice already
        # went out.
        if image_brief:
            try:
                from src.bhai.proactive.dossier_loader import load_user_dossier
                from src.bhai.proactive.tools.nanobanana import generate_image

                phone = f"tg_{chat_id}"
                dossier = load_user_dossier(_get_store(), phone)
                img_dir = DATA_DIR / "reactive_images"
                img = generate_image(
                    image_brief,
                    dossier,
                    api_key=config.nanobanana_api_key,
                    model=config.nanobanana_model,
                    endpoint=config.nanobanana_endpoint,
                    artifacts_dir=img_dir,
                    audit_base_dir=img_dir,
                )
                if img.ok and img.artifact_path:
                    telegram_client.send_photo(
                        chat_id=chat_id, image_path=img.artifact_path
                    )
                    logger.info("Reactive image sent to user=%s", phone_id)
                else:
                    logger.warning(
                        "Reactive image not sent user=%s: %s",
                        phone_id,
                        getattr(img, "error", None),
                    )
            except Exception as img_err:
                logger.error(
                    "Reactive image gen failed for user=%s: %s", phone_id, img_err
                )
        return True

    except Exception as e:
        logger.error(
            "TTS/send failed for user=%s: %s — voice-only mode, no fallback",
            phone_id,
            e,
        )
        return False


def _apply_memory_patches(
    *,
    phone: str,
    phone_id: str,
    store: ConversationStore,
    memory_patches: Optional[Dict[str, Any]],
    prior_memory: Optional[Dict[str, Any]],
) -> None:
    """Persist model-emitted memory deltas into the store.

    ``memory_patches`` is the parsed output of
    ``BaseLLM._parse_memory_patches()`` — either ``None`` (no <memory>
    blocks emitted this turn) or ``{"summary": Optional[str],
    "facts": List[str]}``. New facts are merged + deduplicated against
    the prior fact list via ``merge_facts``. The summary is replaced
    wholesale when present, preserved when ``None``.

    Non-critical: any persistence failure is logged but does not block
    the voice reply (which has already been sent by this point).
    """
    if not memory_patches:
        return

    new_summary = memory_patches.get("summary")
    new_facts = memory_patches.get("facts") or []

    if not new_summary and not new_facts:
        return

    try:
        existing_summary = (prior_memory or {}).get("summary", "")
        existing_facts = (prior_memory or {}).get("facts", []) or []

        merged_summary = new_summary if new_summary else existing_summary
        merged_facts = (
            merge_facts(existing_facts, new_facts) if new_facts else existing_facts
        )

        store.save_memory(phone, merged_summary, merged_facts)
        logger.info(
            "Memory patch applied for user=%s: summary_updated=%s new_facts=%d total_facts=%d",
            phone_id,
            bool(new_summary),
            len(new_facts),
            len(merged_facts),
        )
    except Exception as e:
        logger.error("Memory patch persistence failed for user=%s: %s", phone_id, e)


# ── Main webhook ──────────────────────────────────────────────────────


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    """
    Handle incoming Telegram update.

    Verifies the X-Telegram-Bot-Api-Secret-Token header against
    TELEGRAM_WEBHOOK_SECRET, parses the update, and spawns a background
    task to run the STT → LLM → TTS pipeline. Returns 200 immediately
    (Telegram retries if we don't reply within 60s).
    """
    config = load_config()

    # Secret token verification
    expected_secret = config.telegram_webhook_secret
    if expected_secret and x_telegram_bot_api_secret_token != expected_secret:
        logger.warning("Telegram webhook: bad secret token")
        return Response(status_code=403, content="Forbidden")

    update = await request.json()
    message = update.get("message") or update.get("edited_message")
    if not message:
        # Could be a callback_query, channel_post, etc — ignore for now
        logger.info("Skipping non-message update keys=%s", list(update.keys()))
        return {"ok": True}

    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        logger.warning("Telegram update missing chat.id: %s", update)
        return {"ok": True}

    phone = f"tg_{chat_id}"
    phone_id = _phone_hash(phone)

    # Rate limiting
    if not _check_rate_limit(phone):
        logger.warning("Rate limited user=%s", phone_id)
        return {"ok": True}

    # Voice or text?
    voice = message.get("voice") or message.get("audio")
    body_text = message.get("text", "") or message.get("caption", "")
    is_audio = bool(voice and voice.get("file_id"))
    is_text = bool(body_text) and not is_audio

    logger.info(
        "Message from user=%s voice=%s has_text=%s",
        phone_id,
        bool(voice),
        bool(body_text),
    )

    if not is_audio and not is_text:
        logger.info("Skipping non-processable message from user=%s", phone_id)
        return {"ok": True}

    background_tasks.add_task(
        process_message,
        chat_id=chat_id,
        is_audio=is_audio,
        voice_file_id=voice.get("file_id", "") if voice else "",
        body_text=body_text,
    )
    return {"ok": True}


# ── Health check ───────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "bhai-telegram-webhook"}


# ── Pilot monitoring dashboard (mirrored from twilio_webhook.py) ──────

_DASHBOARD_KEY = _os.getenv("DASHBOARD_SECRET", "bhai-pilot-2026")


def _check_dashboard_key(key: str):
    if key != _DASHBOARD_KEY:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return None


@app.get("/dashboard")
async def dashboard(key: str = ""):
    """Pilot metrics — message counts, response times, failures. No content."""
    auth = _check_dashboard_key(key)
    if auth:
        return auth

    store = _get_store()
    conn = store._conn

    phones = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT phone FROM messages WHERE phone NOT IN ('web_test_user')"
        ).fetchall()
    ]

    users = []
    total_msgs = 0
    total_response_times = []
    total_failures = 0

    for phone in phones:
        rows = conn.execute(
            "SELECT role, timestamp FROM messages WHERE phone = ? ORDER BY timestamp",
            (phone,),
        ).fetchall()

        msg_count = len(rows)
        total_msgs += msg_count
        user_msgs = [r for r in rows if r[0] == "user"]
        asst_msgs = [r for r in rows if r[0] == "assistant"]

        response_times = []
        failures = 0
        for i, (role, ts) in enumerate(rows):
            if role == "user":
                next_asst = None
                for j in range(i + 1, len(rows)):
                    if rows[j][0] == "assistant":
                        next_asst = rows[j]
                        break
                if next_asst:
                    try:
                        user_time = datetime.fromisoformat(ts)
                        asst_time = datetime.fromisoformat(next_asst[1])
                        gap = (asst_time - user_time).total_seconds()
                        if gap < 120:
                            response_times.append(gap)
                        else:
                            failures += 1
                    except Exception:
                        pass
                else:
                    failures += 1

        total_failures += failures
        total_response_times.extend(response_times)

        avg_rt = (
            round(sum(response_times) / len(response_times), 1)
            if response_times
            else None
        )
        phone_hash = hashlib.sha256(phone.encode()).hexdigest()[:12]
        platform = "telegram" if phone.startswith("tg_") else "twilio"

        users.append(
            {
                "phone_hash": phone_hash,
                "platform": platform,
                "message_count": msg_count,
                "user_messages": len(user_msgs),
                "bot_messages": len(asst_msgs),
                "first_message": rows[0][1] if rows else None,
                "last_active": rows[-1][1] if rows else None,
                "avg_response_time_s": avg_rt,
                "failed_responses": failures,
            }
        )

    avg_total = (
        round(sum(total_response_times) / len(total_response_times), 1)
        if total_response_times
        else None
    )

    return {
        "users": users,
        "totals": {
            "total_messages": total_msgs,
            "total_users": len(phones),
            "avg_response_time_s": avg_total,
            "total_failures": total_failures,
        },
    }


@app.get("/debug/{phone_hash}")
async def debug_user(phone_hash: str, key: str = ""):
    """Debug a specific user — timestamps only, no content."""
    auth = _check_dashboard_key(key)
    if auth:
        return auth

    store = _get_store()
    conn = store._conn

    phones = [
        r[0] for r in conn.execute("SELECT DISTINCT phone FROM messages").fetchall()
    ]
    target_phone = None
    for phone in phones:
        if hashlib.sha256(phone.encode()).hexdigest()[:12] == phone_hash:
            target_phone = phone
            break

    if not target_phone:
        return {"error": "user not found"}

    rows = conn.execute(
        "SELECT role, timestamp, session_id FROM messages WHERE phone = ? ORDER BY timestamp",
        (target_phone,),
    ).fetchall()

    timeline = []
    for i, (role, ts, session_id) in enumerate(rows):
        entry = {"role": role, "timestamp": ts, "session_id": session_id}
        if role == "user":
            got_reply = False
            reply_time = None
            for j in range(i + 1, len(rows)):
                if rows[j][0] == "assistant":
                    got_reply = True
                    try:
                        gap = (
                            datetime.fromisoformat(rows[j][1])
                            - datetime.fromisoformat(ts)
                        ).total_seconds()
                        reply_time = round(gap, 1)
                    except Exception:
                        pass
                    break
            entry["got_reply"] = got_reply
            entry["reply_time_s"] = reply_time
        timeline.append(entry)

    return {"phone_hash": phone_hash, "total_messages": len(rows), "timeline": timeline}


@app.get("/conversations/{phone_hash}")
async def conversations(phone_hash: str, key: str = "", format: str = "json"):
    """Full decrypted transcripts. Access is logged. Use format=html for readable view."""
    auth = _check_dashboard_key(key)
    if auth:
        return auth

    logger.warning("TRANSCRIPT ACCESS for user=%s by key holder", phone_hash)

    store = _get_store()
    conn = store._conn

    phones = [
        r[0] for r in conn.execute("SELECT DISTINCT phone FROM messages").fetchall()
    ]
    target_phone = None
    for phone in phones:
        if hashlib.sha256(phone.encode()).hexdigest()[:12] == phone_hash:
            target_phone = phone
            break

    if not target_phone:
        return {"error": "user not found"}

    messages = store.get_recent_messages(target_phone, limit=200)

    if format == "html":
        rows = ""
        last_date = ""
        for m in messages:
            ts = m["timestamp"]
            date_part = ts[:10]
            if date_part != last_date:
                last_date = date_part
                rows += f'<div style="text-align:center;margin:18px 0 8px;color:#888;font-size:13px">{date_part}</div>\n'
            time_part = ts[11:16]
            content = (
                m["content"]
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br>")
            )
            if m["role"] == "user":
                rows += (
                    f'<div style="display:flex;margin:6px 0">'
                    f'<div style="background:#f0f0f0;border-radius:12px;padding:10px 14px;max-width:80%;font-size:15px;line-height:1.5">'
                    f"{content}"
                    f'<div style="font-size:11px;color:#999;margin-top:4px">{time_part}</div>'
                    f"</div></div>\n"
                )
            else:
                rows += (
                    f'<div style="display:flex;justify-content:flex-end;margin:6px 0">'
                    f'<div style="background:#dcf8c6;border-radius:12px;padding:10px 14px;max-width:80%;font-size:15px;line-height:1.5">'
                    f"{content}"
                    f'<div style="font-size:11px;color:#999;margin-top:4px">{time_part} — bhAI</div>'
                    f"</div></div>\n"
                )

        html = (
            f'<!DOCTYPE html><html><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>bhAI — {phone_hash}</title></head>"
            f'<body style="font-family:-apple-system,sans-serif;max-width:600px;margin:0 auto;padding:16px;background:#e5ddd5">'
            f'<div style="background:#075e54;color:white;padding:14px 16px;border-radius:8px;margin-bottom:12px;font-size:16px;font-weight:600">'
            f"bhAI Conversations — {phone_hash} ({len(messages)} messages)</div>"
            f"{rows}"
            f"</body></html>"
        )
        return HTMLResponse(content=html)

    return JSONResponse(
        content={
            "phone_hash": phone_hash,
            "message_count": len(messages),
            "messages": [
                {
                    "role": m["role"],
                    "content": m["content"],
                    "timestamp": m["timestamp"],
                }
                for m in messages
            ],
        },
        media_type="application/json; charset=utf-8",
    )


@app.get("/admin/phones")
async def admin_phones(key: str = ""):
    """Hash-to-phone mapping for pilot admin. Access is logged."""
    auth = _check_dashboard_key(key)
    if auth:
        return auth

    logger.warning("ADMIN PHONE ACCESS by key holder")

    store = _get_store()
    conn = store._conn
    phones = [
        r[0] for r in conn.execute("SELECT DISTINCT phone FROM messages").fetchall()
    ]

    return {
        "users": [
            {"phone_hash": hashlib.sha256(p.encode()).hexdigest()[:12], "phone": p}
            for p in phones
        ]
    }


def _phone_from_hash(phone_hash: str) -> str | None:
    """Reverse-lookup a phone string from its 12-char SHA256 hash."""
    store = _get_store()
    rows = store._conn.execute("SELECT DISTINCT phone FROM messages").fetchall()
    for (p,) in rows:
        if hashlib.sha256(p.encode()).hexdigest()[:12] == phone_hash:
            return p
    return None


@app.get("/admin/memory/{phone_hash}")
async def admin_memory(phone_hash: str, key: str = ""):
    """Inspect rolling summary + extracted facts for one user. Access is logged.

    Used to verify that the summarizer captured key context (e.g. that a user
    does stitching, has a specific child situation, etc.) — particularly
    after a /admin/migrate, where prior conversation history is re-keyed
    but the rolling memory may still reflect the old session-window only.
    """
    auth = _check_dashboard_key(key)
    if auth:
        return auth

    target_phone = _phone_from_hash(phone_hash)
    if not target_phone:
        return JSONResponse({"error": "user not found"}, status_code=404)

    logger.warning("ADMIN MEMORY ACCESS for user=%s by key holder", phone_hash)

    store = _get_store()
    memory = store.get_memory(target_phone)
    if memory is None:
        return {
            "phone_hash": phone_hash,
            "summary": None,
            "facts": [],
            "last_updated": None,
        }

    return {
        "phone_hash": phone_hash,
        "summary": memory["summary"],
        "facts": memory["facts"],
        "last_updated": memory["last_updated"],
    }


@app.post("/admin/backfill-nudges")
async def admin_backfill_nudges(
    key: str = "",
    dry_run: bool = True,
    days: int = 30,
):
    """One-shot: seed nudge_log from existing assistant messages.

    Pilot users pre-date the nudge_log feedback table. The actual nudges
    are already in the messages transcript, so this re-detects the
    assistant messages that were nudges (slot-window timestamp + > 30 min
    gap from previous message) and pairs each with the user's reaction
    (first reply inside the 24h window), seeding nudge_log with original
    timestamps. Delegates to proactive.monitor.reconstruct_nudge_log — the
    single source of the reconstruction heuristic (also used by the CLI).

    Defaults to ``dry_run=true`` — pass ``dry_run=false`` to actually
    write. Idempotent: re-runs skip rows already inserted.

    Usage:
        curl -X POST 'https://<host>/admin/backfill-nudges?key=<KEY>&dry_run=true'
        curl -X POST 'https://<host>/admin/backfill-nudges?key=<KEY>&dry_run=false'
    """
    auth = _check_dashboard_key(key)
    if auth:
        return auth

    # Import lazily so the webhook module doesn't pull config at import
    # time (matches the existing pattern in admin_memory etc.).
    from src.bhai.config import load_config
    from src.bhai.proactive.monitor import reconstruct_nudge_log

    cfg = load_config()
    store = _get_store()

    per_phone_counts = reconstruct_nudge_log(store, cfg, days=days, dry_run=dry_run)

    totals = {"nudges": 0, "with_reaction": 0, "inserted": 0, "skipped_existing": 0}
    per_phone: list[dict] = []
    for phone, c in per_phone_counts.items():
        phone_hash = hashlib.sha256(phone.encode()).hexdigest()[:12]
        per_phone.append(
            {
                "phone_hash": phone_hash,
                "scanned": c.scanned,
                "nudges": c.nudges,
                "with_reaction": c.with_reaction,
                "inserted": c.inserted,
                "skipped_existing": c.skipped_existing,
            }
        )
        totals["nudges"] += c.nudges
        totals["with_reaction"] += c.with_reaction
        totals["inserted"] += c.inserted
        totals["skipped_existing"] += c.skipped_existing

    logger.warning(
        "ADMIN BACKFILL-NUDGE-LOG dry_run=%s days=%d → %s",
        dry_run,
        days,
        totals,
    )
    return {
        "dry_run": dry_run,
        "days": days,
        "totals": totals,
        "per_phone": per_phone,
    }


@app.post("/admin/reset/{phone_hash}")
async def admin_reset(phone_hash: str, key: str = ""):
    """Wipe one user's messages, memory, and nudge tracking.

    After this, the next /start from this user triggers the onboarding
    intro again. Use sparingly — meant for pilot testing.
    """
    auth = _check_dashboard_key(key)
    if auth:
        return auth

    target_phone = _phone_from_hash(phone_hash)
    if not target_phone:
        return JSONResponse({"error": "user not found"}, status_code=404)

    store = _get_store()
    counts = store.delete_user(target_phone)
    logger.warning(
        "ADMIN RESET for user=%s by key holder — %s",
        phone_hash,
        counts,
    )
    return {"phone_hash": phone_hash, **counts}


@app.post("/admin/migrate")
async def admin_migrate(
    key: str = "",
    from_phone: str = "",
    to_phone: str = "",
):
    """Move all of one user's data to a new phone identifier.

    Use this when a pilot user who chatted on Twilio/WhatsApp moves to
    Telegram — call once with the original phone (e.g. "+919321125042")
    and the new tg_<chat_id> identifier. After migration, /start on
    Telegram triggers the re-onboarding branch (recap + follow-up) using
    the imported memory and history.

    Both `from_phone` and `to_phone` are required as query params.
    """
    auth = _check_dashboard_key(key)
    if auth:
        return auth

    if not from_phone or not to_phone:
        return JSONResponse(
            {"error": "from_phone and to_phone are both required"}, status_code=400
        )
    if from_phone == to_phone:
        return JSONResponse(
            {"error": "from_phone and to_phone must differ"}, status_code=400
        )

    store = _get_store()
    counts = store.merge_user(from_phone=from_phone, to_phone=to_phone)
    from_hash = hashlib.sha256(from_phone.encode()).hexdigest()[:12]
    to_hash = hashlib.sha256(to_phone.encode()).hexdigest()[:12]
    logger.warning(
        "ADMIN MIGRATE from=%s → to=%s by key holder — %s",
        from_hash,
        to_hash,
        counts,
    )
    return {"from_hash": from_hash, "to_hash": to_hash, **counts}


@app.post("/admin/send-message/{phone_hash}")
async def admin_send_message(phone_hash: str, key: str = "", text: str = ""):
    """Send a literal text message to a user, bypassing the LLM.

    Use this for trust-repair / correction messages where bhAI's normal
    generation pipeline (which can hallucinate) must NOT be in the loop.
    The message is sent verbatim and saved into the conversation history
    as an `assistant` message so future LLM context sees it.

    Telegram-only. The text is delivered via Telegram's sendMessage API,
    not as a voice note — the use cases for this endpoint are short
    corrections, not natural conversation turns.
    """
    auth = _check_dashboard_key(key)
    if auth:
        return auth

    if not text or not text.strip():
        return JSONResponse(
            {"error": "text query param is required and cannot be empty"},
            status_code=400,
        )

    target_phone = _phone_from_hash(phone_hash)
    if not target_phone:
        return JSONResponse({"error": "user not found"}, status_code=404)

    if not target_phone.startswith("tg_"):
        return JSONResponse(
            {"error": "non-Telegram users not supported by this endpoint"},
            status_code=400,
        )

    try:
        chat_id = int(target_phone[len("tg_") :])
    except ValueError:
        return JSONResponse({"error": "bad chat_id"}, status_code=400)

    config = load_config()
    telegram_client = TelegramClient(bot_token=config.telegram_bot_token)
    try:
        result = telegram_client.send_text(chat_id, text)
    except Exception as e:
        logger.exception("ADMIN SEND-MESSAGE failed for user=%s: %s", phone_hash, e)
        return JSONResponse({"error": f"telegram send failed: {e}"}, status_code=502)

    store = _get_store()
    session_id, _ = store.get_or_create_session(target_phone)
    store.save_message(target_phone, "assistant", text, session_id)

    logger.warning(
        "ADMIN SEND-MESSAGE to user=%s chars=%d by key holder",
        phone_hash,
        len(text),
    )
    return {
        "phone_hash": phone_hash,
        "chars": len(text),
        "telegram_message_id": result.get("message_id"),
        "ok": result.get("ok", False),
    }


@app.post("/admin/throttle-nudge/{phone_hash}")
async def admin_throttle_nudge(phone_hash: str, key: str = "", hours: int = 0):
    """Set or clear a per-user nudge throttle.

    When `hours` > 0, bhAI will only nudge this user if no nudge of any slot
    fired within the last `hours` hours. Use `hours=48` for "once every 2 days"
    (the User N case — they explicitly asked for less frequent contact).

    Pass `hours=0` (or negative) to clear an existing throttle and return the
    user to the default twice-daily schedule.
    """
    auth = _check_dashboard_key(key)
    if auth:
        return auth

    target_phone = _phone_from_hash(phone_hash)
    if not target_phone:
        return JSONResponse({"error": "user not found"}, status_code=404)

    store = _get_store()
    store.set_throttle_hours(target_phone, hours)
    current = store.get_throttle_hours(target_phone)

    logger.warning(
        "ADMIN THROTTLE-NUDGE for user=%s hours=%s (effective=%s) by key holder",
        phone_hash,
        hours,
        current,
    )
    return {
        "phone_hash": phone_hash,
        "throttle_hours": current,
        "cleared": current is None,
    }


@app.post("/admin/test-nudge/{phone_hash}")
async def admin_test_nudge(phone_hash: str, key: str = "", slot: str = "morning"):
    """Fire one v2 nudge to one user immediately, ignoring schedule + rate-limit.

    Runs the full v2 ProactiveThinker (brainstorm → critique → tools → draft →
    judge) against the user's REAL dossier (threads + memory), so this shows
    exactly what proactive mode would say for them. `slot`: 'morning'/'night'
    (substantive) or 'afternoon' (joke). Bypasses NUDGE_ENABLED + rate-limit.
    """
    auth = _check_dashboard_key(key)
    if auth:
        return auth

    if slot not in ("morning", "afternoon", "night"):
        return JSONResponse(
            {"error": "slot must be 'morning', 'afternoon', or 'night'"},
            status_code=400,
        )

    target_phone = _phone_from_hash(phone_hash)
    if not target_phone:
        return JSONResponse({"error": "user not found"}, status_code=404)

    if not target_phone.startswith("tg_"):
        return JSONResponse(
            {"error": "non-Telegram users cannot receive nudges"}, status_code=400
        )

    try:
        chat_id = int(target_phone[len("tg_") :])
    except ValueError:
        return JSONResponse({"error": "bad chat_id"}, status_code=400)

    config = load_config()
    store = _get_store()

    from inference.webhooks.nudges import _generate_nudge_v2

    try:
        cand = _generate_nudge_v2(
            phone=target_phone, slot=slot, store=store, config=config
        )
    except Exception as e:
        logger.exception("Test nudge (v2) generation failed: %s", e)
        return JSONResponse({"error": f"generation failed: {e}"}, status_code=500)

    if not cand or not cand.text:
        return JSONResponse({"error": "empty nudge text"}, status_code=500)

    logger.warning(
        "ADMIN TEST NUDGE v2 user=%s slot=%s cat=%s len=%d",
        phone_hash,
        slot,
        cand.category,
        len(cand.text),
    )
    _send_nudge(chat_id, slot, cand.text, cand.text_artifact, cand.artifact_path)
    store.record_nudge_outcome(
        target_phone, slot, cand.thread_slug, category=cand.category, text=cand.text
    )
    return {
        "phone_hash": phone_hash,
        "slot": slot,
        "category": cand.category,
        "thread": cand.thread_slug,
        "text": cand.text,
        "text_artifact": cand.text_artifact,
        "image": str(cand.artifact_path) if cand.artifact_path else None,
        "sent": True,
    }
