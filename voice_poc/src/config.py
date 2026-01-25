import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
CONTEXT_DIR = BASE_DIR / "company_context"
OUTPUTS_DIR = BASE_DIR / "outputs"
DEBUG_LOG_PATH = Path("/Users/sundarraghavanl/PycharmProjects/bhAI_voice_bot/.cursor/debug.log")


# #region agent log
def _debug_log(location: str, message: str, data: dict, *, run_id: str, hypothesis_id: str) -> None:
    try:
        payload = {
            "sessionId": "debug-session",
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with DEBUG_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
    except Exception:
        pass
# #endregion


@dataclass
class Config:
    openai_api_key: str
    openai_model: str
    sample_rate: int = 16000
    sarvam_api_key: str = ""
    sarvam_stt_url: str = "https://api.sarvam.ai/speech-to-text"
    sarvam_stt_model: str = "saarika:v2.5"
    sarvam_tts_url: str = "https://api.sarvam.ai/text-to-speech"
    sarvam_tts_voice: str = "manisha"
    sarvam_tts_language: str = "hi-IN"
    sarvam_tts_sample_rate: int | None = None
    meta_wa_token: str = ""
    meta_phone_number_id: str = ""
    meta_waba_id: str = ""
    meta_verify_token: str = ""
    meta_api_version: str = "v22.0"


def load_config() -> Config:
    # Load .env from repo root if present (uv does not auto-load)
    env_path = BASE_DIR / ".env"
    env_loaded = load_dotenv(env_path, override=False)
    # #region agent log
    _debug_log(
        "config.py:load_config:dotenv",
        "Attempted to load .env",
        {"env_path": str(env_path), "env_loaded": bool(env_loaded)},
        run_id="pre-fix",
        hypothesis_id="H1",
    )
    # #endregion
    # #region agent log
    _debug_log(
        "config.py:load_config:entry",
        "Loading config and environment",
        {
            "cwd": os.getcwd(),
            "has_openai_key": bool(os.getenv("OPENAI_API_KEY")),
            "has_sarvam_key": bool(os.getenv("SARVAM_API_KEY")),
        },
        run_id="pre-fix",
        hypothesis_id="H1",
    )
    # #endregion
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY missing. Set it in environment or .env.")

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    sarvam_key = os.getenv("SARVAM_API_KEY", "")
    sarvam_stt_url = os.getenv("SARVAM_STT_URL", "https://api.sarvam.ai/speech-to-text")
    sarvam_stt_model = os.getenv("SARVAM_STT_MODEL", "saarika:v2.5")
    sarvam_tts_url = os.getenv("SARVAM_TTS_URL", "https://api.sarvam.ai/text-to-speech")
    sarvam_tts_voice = os.getenv("SARVAM_TTS_VOICE", "manisha")
    sarvam_tts_language = os.getenv("SARVAM_TTS_LANGUAGE", "hi-IN")
    sarvam_tts_sample_rate = os.getenv("SARVAM_TTS_SAMPLE_RATE")
    sarvam_tts_sample_rate_val = int(sarvam_tts_sample_rate) if sarvam_tts_sample_rate else None
    meta_wa_token = os.getenv("META_WA_TOKEN", "")
    meta_phone_number_id = os.getenv("META_PHONE_NUMBER_ID", "")
    meta_waba_id = os.getenv("META_WABA_ID", "")
    meta_verify_token = os.getenv("META_VERIFY_TOKEN", "")
    meta_api_version = os.getenv("META_API_VERSION", "v22.0")
    # #region agent log
    _debug_log(
        "config.py:load_config:resolved",
        "Resolved config env values",
        {
            "sarvam_key_present": bool(sarvam_key),
            "sarvam_stt_url": sarvam_stt_url,
            "sarvam_tts_url": sarvam_tts_url,
        },
        run_id="pre-fix",
        hypothesis_id="H1",
    )
    # #endregion
    return Config(
        openai_api_key=api_key,
        openai_model=model,
        sarvam_api_key=sarvam_key,
        sarvam_stt_url=sarvam_stt_url,
        sarvam_stt_model=sarvam_stt_model,
        sarvam_tts_url=sarvam_tts_url,
        sarvam_tts_voice=sarvam_tts_voice,
        sarvam_tts_language=sarvam_tts_language,
        sarvam_tts_sample_rate=sarvam_tts_sample_rate_val,
        meta_wa_token=meta_wa_token,
        meta_phone_number_id=meta_phone_number_id,
        meta_waba_id=meta_waba_id,
        meta_verify_token=meta_verify_token,
        meta_api_version=meta_api_version,
    )

