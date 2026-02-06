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

    # OpenAI
    openai_api_key: str
    openai_model: str = "gpt-4o-mini"

    # Audio
    sample_rate: int = 16000

    # Sarvam AI
    sarvam_api_key: str = ""
    sarvam_stt_url: str = "https://api.sarvam.ai/speech-to-text"
    sarvam_stt_model: str = "saarika:v2.5"
    sarvam_tts_url: str = "https://api.sarvam.ai/text-to-speech"
    sarvam_tts_voice: str = "manisha"
    sarvam_tts_language: str = "hi-IN"
    sarvam_tts_sample_rate: Optional[int] = None

    # WhatsApp (Meta)
    meta_wa_token: str = ""
    meta_phone_number_id: str = ""
    meta_waba_id: str = ""
    meta_verify_token: str = ""
    meta_api_version: str = "v22.0"


def load_config(env_path: Optional[Path] = None) -> Config:
    """
    Load configuration from environment variables.
    Optionally loads from a .env file first.
    """
    if env_path is None:
        env_path = ROOT_DIR / ".env"

    if env_path.exists():
        load_dotenv(env_path, override=False)

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY missing. Set it in environment or .env.")

    sarvam_tts_sample_rate = os.getenv("SARVAM_TTS_SAMPLE_RATE")

    return Config(
        openai_api_key=api_key,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        sarvam_api_key=os.getenv("SARVAM_API_KEY", ""),
        sarvam_stt_url=os.getenv("SARVAM_STT_URL", "https://api.sarvam.ai/speech-to-text"),
        sarvam_stt_model=os.getenv("SARVAM_STT_MODEL", "saarika:v2.5"),
        sarvam_tts_url=os.getenv("SARVAM_TTS_URL", "https://api.sarvam.ai/text-to-speech"),
        sarvam_tts_voice=os.getenv("SARVAM_TTS_VOICE", "manisha"),
        sarvam_tts_language=os.getenv("SARVAM_TTS_LANGUAGE", "hi-IN"),
        sarvam_tts_sample_rate=int(sarvam_tts_sample_rate) if sarvam_tts_sample_rate else None,
        meta_wa_token=os.getenv("META_WA_TOKEN", ""),
        meta_phone_number_id=os.getenv("META_PHONE_NUMBER_ID", ""),
        meta_waba_id=os.getenv("META_WABA_ID", ""),
        meta_verify_token=os.getenv("META_VERIFY_TOKEN", ""),
        meta_api_version=os.getenv("META_API_VERSION", "v22.0"),
    )
