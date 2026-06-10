"""
Configuration management for bhAI voice bot.
Loads settings from environment variables and .env file.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Directory paths
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
KNOWLEDGE_BASE_DIR = ROOT_DIR / "knowledge_base"
DATA_DIR = ROOT_DIR / "data"
INFERENCE_OUTPUTS_DIR = ROOT_DIR / "inference" / "outputs"


@dataclass
class Config:
    """Application configuration loaded from environment."""

    # LLM backend: "sarvam", "openai", or "claude"
    llm_backend: str = "sarvam"

    # OpenAI (only needed when llm_backend="openai")
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Audio
    sample_rate: int = 16000

    # Sarvam AI
    sarvam_api_key: str = ""
    sarvam_llm_model: str = "sarvam-105b"
    sarvam_llm_url: str = "https://api.sarvam.ai/v1"
    sarvam_stt_url: str = "https://api.sarvam.ai/speech-to-text"
    sarvam_stt_model: str = "saaras:v3"
    sarvam_tts_url: str = "https://api.sarvam.ai/text-to-speech"
    sarvam_tts_model: str = "bulbul:v3"
    sarvam_tts_voice: str = "suhani"
    sarvam_tts_language: str = "hi-IN"
    sarvam_tts_sample_rate: Optional[int] = None

    # Twilio WhatsApp
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_number: str = ""  # e.g. "whatsapp:+14155238886"
    base_url: str = ""  # Public URL for serving audio (e.g. ngrok URL)

    # Telegram Bot
    telegram_bot_token: str = ""  # from @BotFather
    telegram_webhook_secret: str = ""  # for X-Telegram-Bot-Api-Secret-Token header
    # Public URL the webhook is reachable at. Resolved at runtime: explicit
    # WEBHOOK_PUBLIC_URL wins, else Railway's auto-injected RAILWAY_PUBLIC_DOMAIN.
    webhook_public_url: str = ""
    railway_public_domain: str = ""
    webhook_watchdog_interval_seconds: int = 600  # 10 min

    # Claude / Anthropic (only needed when llm_backend="claude")
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5-20251001"

    # ElevenLabs TTS
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""  # Vidhi's cloned voice ID
    elevenlabs_model_id: str = "eleven_multilingual_v2"
    elevenlabs_stability: float = 0.5
    elevenlabs_similarity_boost: float = 0.75
    elevenlabs_style: float = 0.4
    elevenlabs_speed: float = 1.0
    tts_backend: str = "sarvam"  # "sarvam" or "elevenlabs"

    # System prompt version — loaded from src/bhai/llm/prompts/{version}.md
    prompt_version: str = "current"

    # cot/out structured output: how many times to re-call the LLM when its
    # JSON can't be parsed before giving up to the safe canned fallback.
    llm_json_max_attempts: int = 3

    # Resilience
    ack_enabled: bool = True  # Send immediate ack on voice notes
    retry_max_attempts: int = 3  # Per-call retry attempts
    queue_max_attempts: int = 5  # Background queue retry attempts
    faq_cache_threshold: float = 0.6  # Jaccard similarity for FAQ match

    # KB router — selects which helpdesk/*.md files to inject per turn
    # instead of stuffing the entire KB into every system prompt.
    # Backend "haiku" uses Claude Haiku 4.5 with prompt caching (recommended;
    # falls back to keyword if ANTHROPIC_API_KEY is missing or the call errors).
    # Backend "keyword" uses the pure-Python KBRouter (sync, no API).
    kb_router_enabled: bool = True
    kb_router_backend: str = "haiku"  # "haiku" | "keyword"
    kb_router_top_n: int = 3
    kb_router_threshold: float = 0.25  # used only by the keyword backend

    # Proactive nudges (option B follow-ups)
    nudge_enabled: bool = False  # Master kill switch — must be opted in
    nudge_phones: str = ""  # Comma-separated phone hashes allowed to receive nudges
    nudge_morning_hour_ist: int = 10  # Local IST hour for morning check-in
    nudge_afternoon_hour_ist: int = 14  # Local IST hour for the afternoon joke
    nudge_night_hour_ist: int = 21  # Local IST hour for night check-in
    nudge_window_minutes: int = 30  # Firing window width around each slot
    nudge_check_interval_seconds: int = 300  # How often the loop wakes
    nudge_active_user_days: int = 7  # Only nudge users active in last N days

    # v2 proactive thinking agent — tool API keys.
    # nanobanana = Google Gemini image generation (kickoff naming). We accept
    # any of NANOBANANA_API_KEY / GEMINI_API_KEY / GOOGLE_GENAI_API_KEY in env
    # so whichever name the operator chose in .env just works. The model name
    # is configurable too — defaults to the current "nano-banana" Flash image
    # model but can be overridden as the API evolves.
    nanobanana_api_key: str = ""
    # Default to the stable Flash image model. Available alternatives at the
    # time of writing (confirmed via ListModels against a real key):
    #   - gemini-2.5-flash-image (stable Flash, our default — cheapest)
    #   - gemini-3.1-flash-image (newer Flash, similar cost)
    #   - gemini-3-pro-image / nano-banana-pro-preview (Pro tier, higher
    #     quality, higher cost — worth A/B-testing for production once the
    #     pipeline is validated)
    nanobanana_model: str = "gemini-2.5-flash-image"
    nanobanana_endpoint: str = "https://generativelanguage.googleapis.com/v1beta/models"
    # Google Programmable Search — separate API key + Custom Search Engine ID.
    # The CSE must be created in the Google Cloud Console (one-time setup).
    # If either is missing, web_search returns a clear "not configured" error
    # rather than failing the whole agent loop.
    google_search_api_key: str = ""
    google_search_cse_id: str = ""
    # Reactive web_search (Claude server-side tool).
    # When enabled, ClaudeLLM passes a web_search tool to the Anthropic Messages
    # API so the model can ground specifics it doesn't know (local clinics,
    # current scheme details, "box cricket venues in Bandra" etc.) instead of
    # confabulating or punting the user to Google. Anthropic enforces the
    # per-call cap server-side via `max_uses`. Default off; enable in dev first.
    web_search_enabled: bool = False
    web_search_max_uses_per_call: int = 3
    # Tool identifier — Anthropic versions this per release. Override via
    # WEB_SEARCH_TOOL_NAME if a newer version ships.
    web_search_tool_name: str = "web_search_20250305"

    # Azure / SharePoint (for transcription pipeline)
    azure_tenant_id: str = ""
    azure_app_client_id: str = ""
    sharepoint_hostname: str = "tinymiraclesnl.sharepoint.com"

    # Escalation emails (Gmail API + OAuth 2.0) — when ESCALATE: true fires,
    # send an email to the impact team via the Gmail HTTPS API. SMTP doesn't
    # work from Railway (outbound 25/465/587 blocked at the platform level).
    # escalation_enabled auto-flips false if OAuth credentials are missing so
    # dev/test runs never silently try to send.
    # Capture the refresh token once via: uv run python scripts/gmail_oauth_setup.py
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_refresh_token: str = ""
    gmail_sender_email: str = ""  # the Workspace account that owns the refresh token
    # Default escalation recipients — the mental_health / unknown-category TO.
    # Just Rishi (rishikesh@); Anu is CC via escalation_impact_head, not TO.
    escalation_recipients: tuple = ()
    # Per-office govt-docs routing. Empty tuple → falls back to default.
    escalation_recipients_docs_bc: tuple = ()
    escalation_recipients_docs_midc: tuple = ()
    # Workplace grievances (supervisor/pay/harassment-at-work) → HR (Simran).
    escalation_recipients_workplace: tuple = ()
    # Always-on CC — every escalation email, regardless of category. This is
    # the OPERATOR address (Sundar): he CCs all escalations to confirm the
    # email pipeline is working. Comma-separated.
    escalation_cc: tuple = ()
    # Impact-team head (Anu). CC'd on every category WITHIN the impact team's
    # domain — docs (Priti/Dinesh) and mental_health (Rishi) — but NOT on
    # workplace (HR/Simran is outside the impact team). Anu heads the team
    # that Rishi, Priti, and Dinesh are part of.
    escalation_impact_head: tuple = ()
    escalation_enabled: bool = False


def load_config(env_path: Optional[Path] = None) -> Config:
    """
    Load configuration from environment variables.
    Optionally loads from a .env file first.
    """
    if env_path is None:
        env_path = ROOT_DIR / ".env"

    if env_path.exists():
        load_dotenv(env_path, override=False)

    sarvam_tts_sample_rate = os.getenv("SARVAM_TTS_SAMPLE_RATE")

    return Config(
        llm_backend=os.getenv("LLM_BACKEND", "sarvam"),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        sarvam_api_key=os.getenv("SARVAM_API_KEY", ""),
        sarvam_llm_model=os.getenv("SARVAM_LLM_MODEL", "sarvam-105b"),
        sarvam_llm_url=os.getenv("SARVAM_LLM_URL", "https://api.sarvam.ai/v1"),
        sarvam_stt_url=os.getenv(
            "SARVAM_STT_URL", "https://api.sarvam.ai/speech-to-text"
        ),
        sarvam_stt_model=os.getenv("SARVAM_STT_MODEL", "saaras:v3"),
        sarvam_tts_url=os.getenv(
            "SARVAM_TTS_URL", "https://api.sarvam.ai/text-to-speech"
        ),
        sarvam_tts_model=os.getenv("SARVAM_TTS_MODEL", "bulbul:v3"),
        sarvam_tts_voice=os.getenv("SARVAM_TTS_VOICE", "suhani"),
        sarvam_tts_language=os.getenv("SARVAM_TTS_LANGUAGE", "hi-IN"),
        sarvam_tts_sample_rate=(
            int(sarvam_tts_sample_rate) if sarvam_tts_sample_rate else None
        ),
        twilio_account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
        twilio_auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
        twilio_whatsapp_number=os.getenv("TWILIO_WHATSAPP_NUMBER", ""),
        base_url=os.getenv("BASE_URL", ""),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_webhook_secret=os.getenv("TELEGRAM_WEBHOOK_SECRET", ""),
        webhook_public_url=os.getenv("WEBHOOK_PUBLIC_URL", ""),
        railway_public_domain=os.getenv("RAILWAY_PUBLIC_DOMAIN", ""),
        webhook_watchdog_interval_seconds=int(
            os.getenv("WEBHOOK_WATCHDOG_INTERVAL_SECONDS", "600")
        ),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
        elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY", ""),
        elevenlabs_voice_id=os.getenv("ELEVENLABS_VOICE_ID", ""),
        elevenlabs_model_id=os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2"),
        elevenlabs_stability=float(os.getenv("ELEVENLABS_STABILITY", "0.5")),
        elevenlabs_similarity_boost=float(
            os.getenv("ELEVENLABS_SIMILARITY_BOOST", "0.75")
        ),
        elevenlabs_style=float(os.getenv("ELEVENLABS_STYLE", "0.4")),
        elevenlabs_speed=float(os.getenv("ELEVENLABS_SPEED", "1.0")),
        tts_backend=os.getenv("TTS_BACKEND", "sarvam"),
        prompt_version=os.getenv("PROMPT_VERSION", "current"),
        llm_json_max_attempts=int(os.getenv("LLM_JSON_MAX_ATTEMPTS", "3")),
        ack_enabled=os.getenv("ACK_ENABLED", "true").lower() == "true",
        retry_max_attempts=int(os.getenv("RETRY_MAX_ATTEMPTS", "3")),
        queue_max_attempts=int(os.getenv("QUEUE_MAX_ATTEMPTS", "5")),
        faq_cache_threshold=float(os.getenv("FAQ_CACHE_THRESHOLD", "0.6")),
        kb_router_enabled=os.getenv("KB_ROUTER_ENABLED", "true").lower() == "true",
        kb_router_backend=os.getenv("KB_ROUTER_BACKEND", "haiku"),
        kb_router_top_n=int(os.getenv("KB_ROUTER_TOP_N", "3")),
        kb_router_threshold=float(os.getenv("KB_ROUTER_THRESHOLD", "0.25")),
        nudge_enabled=os.getenv("NUDGE_ENABLED", "false").lower() == "true",
        nudge_phones=os.getenv("NUDGE_PHONES", ""),
        nudge_morning_hour_ist=int(os.getenv("NUDGE_MORNING_HOUR_IST", "10")),
        nudge_afternoon_hour_ist=int(os.getenv("NUDGE_AFTERNOON_HOUR_IST", "14")),
        nudge_night_hour_ist=int(os.getenv("NUDGE_NIGHT_HOUR_IST", "21")),
        nudge_window_minutes=int(os.getenv("NUDGE_WINDOW_MINUTES", "30")),
        nudge_check_interval_seconds=int(
            os.getenv("NUDGE_CHECK_INTERVAL_SECONDS", "300")
        ),
        nudge_active_user_days=int(os.getenv("NUDGE_ACTIVE_USER_DAYS", "7")),
        # nanobanana / Gemini image gen — accept any of four env-var names.
        # GOOGLE_API_KEY is the generic Google name; we check it last so a
        # service-specific name (NANOBANANA / GEMINI / GOOGLE_GENAI) wins
        # if both happen to be set.
        nanobanana_api_key=(
            os.getenv("NANOBANANA_API_KEY")
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_GENAI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or ""
        ),
        nanobanana_model=os.getenv("NANOBANANA_MODEL", "gemini-2.5-flash-image"),
        nanobanana_endpoint=os.getenv(
            "NANOBANANA_ENDPOINT",
            "https://generativelanguage.googleapis.com/v1beta/models",
        ),
        # Google Search shares Google's project API key by default — same
        # GOOGLE_API_KEY works for both Custom Search and Gemini once Custom
        # Search API is enabled in the project. Operator can override with
        # a dedicated GOOGLE_SEARCH_API_KEY if they want separate quotas.
        google_search_api_key=(
            os.getenv("GOOGLE_SEARCH_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        ),
        google_search_cse_id=os.getenv("GOOGLE_SEARCH_CSE_ID", ""),
        web_search_enabled=os.getenv("WEB_SEARCH_ENABLED", "false").lower() == "true",
        web_search_max_uses_per_call=int(
            os.getenv("WEB_SEARCH_MAX_USES_PER_CALL", "3")
        ),
        web_search_tool_name=os.getenv("WEB_SEARCH_TOOL_NAME", "web_search_20250305"),
        azure_tenant_id=os.getenv("AZURE_TENANT_ID", ""),
        azure_app_client_id=os.getenv("AZURE_APP_CLIENT_ID", ""),
        sharepoint_hostname=os.getenv(
            "SHAREPOINT_HOSTNAME", "tinymiraclesnl.sharepoint.com"
        ),
        gmail_client_id=os.getenv("GMAIL_CLIENT_ID", ""),
        gmail_client_secret=os.getenv("GMAIL_CLIENT_SECRET", ""),
        gmail_refresh_token=os.getenv("GMAIL_REFRESH_TOKEN", ""),
        gmail_sender_email=os.getenv("GMAIL_SENDER_EMAIL", ""),
        escalation_recipients=tuple(
            addr.strip()
            for addr in os.getenv(
                "ESCALATION_RECIPIENTS",
                "rishikesh@tinymiracles.com",
            ).split(",")
            if addr.strip()
        ),
        escalation_recipients_docs_bc=tuple(
            addr.strip()
            for addr in os.getenv(
                "ESCALATION_RECIPIENTS_DOCS_BC",
                "priti@tinymiracles.com",
            ).split(",")
            if addr.strip()
        ),
        escalation_recipients_docs_midc=tuple(
            addr.strip()
            for addr in os.getenv(
                "ESCALATION_RECIPIENTS_DOCS_MIDC",
                "dinesh@tinymiracles.com",
            ).split(",")
            if addr.strip()
        ),
        escalation_recipients_workplace=tuple(
            addr.strip()
            for addr in os.getenv(
                "ESCALATION_RECIPIENTS_WORKPLACE",
                "simran@tinymiracles.com",
            ).split(",")
            if addr.strip()
        ),
        escalation_cc=tuple(
            addr.strip()
            for addr in os.getenv(
                "ESCALATION_CC",
                "sundar@tinymiracles.com",
            ).split(",")
            if addr.strip()
        ),
        escalation_impact_head=tuple(
            addr.strip()
            for addr in os.getenv(
                "ESCALATION_IMPACT_HEAD",
                "anu@tinymiracles.com",
            ).split(",")
            if addr.strip()
        ),
        escalation_enabled=(
            bool(os.getenv("GMAIL_CLIENT_ID"))
            and bool(os.getenv("GMAIL_CLIENT_SECRET"))
            and bool(os.getenv("GMAIL_REFRESH_TOKEN"))
            and bool(os.getenv("GMAIL_SENDER_EMAIL"))
            and os.getenv("ESCALATION_ENABLED", "true").lower() == "true"
        ),
    )
