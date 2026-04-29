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

    # Resilience
    ack_enabled: bool = True  # Send immediate ack on voice notes
    retry_max_attempts: int = 3  # Per-call retry attempts
    queue_max_attempts: int = 5  # Background queue retry attempts
    faq_cache_threshold: float = 0.6  # Jaccard similarity for FAQ match

    # Azure / SharePoint (for transcription pipeline)
    azure_tenant_id: str = ""
    azure_app_client_id: str = ""
    sharepoint_hostname: str = "tinymiraclesnl.sharepoint.com"


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
        ack_enabled=os.getenv("ACK_ENABLED", "true").lower() == "true",
        retry_max_attempts=int(os.getenv("RETRY_MAX_ATTEMPTS", "3")),
        queue_max_attempts=int(os.getenv("QUEUE_MAX_ATTEMPTS", "5")),
        faq_cache_threshold=float(os.getenv("FAQ_CACHE_THRESHOLD", "0.6")),
        azure_tenant_id=os.getenv("AZURE_TENANT_ID", ""),
        azure_app_client_id=os.getenv("AZURE_APP_CLIENT_ID", ""),
        sharepoint_hostname=os.getenv(
            "SHAREPOINT_HOSTNAME", "tinymiraclesnl.sharepoint.com"
        ),
    )
