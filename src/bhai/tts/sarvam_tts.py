"""
Sarvam AI TTS backend implementation.
Uses Sarvam's TTS API for natural Hindi speech synthesis.
"""

import base64
import re
from pathlib import Path
from typing import Any, Dict

import requests

from ..config import Config
from ..resilience.retry import retry_with_backoff
from .base import BaseTTS

# Unicode-block start/end pairs for the Indic scripts Sarvam supports.
# Used by `detect_language_code` to pick the right `target_language_code`
# per TTS call. Without this, all replies (Tamil, Telugu, Bengali, etc.)
# went through Sarvam's Hindi voice model and either mispronounced the
# text or read English punctuation literally (e.g. "Sundar!" → "Sundar
# factorial" in the 2026-05-27 Tamil dev test). Sarvam's bulbul:v3
# supports all 11 Indian languages natively; we just have to TELL it.
_SCRIPT_RANGES = (
    ("devanagari", 0x0900, 0x097F),  # Hindi, Marathi, Sanskrit, Nepali
    ("bengali", 0x0980, 0x09FF),  # Bengali + Assamese
    ("gurmukhi", 0x0A00, 0x0A7F),  # Punjabi
    ("gujarati", 0x0A80, 0x0AFF),
    ("odia", 0x0B00, 0x0B7F),
    ("tamil", 0x0B80, 0x0BFF),
    ("telugu", 0x0C00, 0x0C7F),
    ("kannada", 0x0C80, 0x0CFF),
    ("malayalam", 0x0D00, 0x0D7F),
)

# Map dominant script → Sarvam target_language_code.
# Marathi shares Devanagari with Hindi; we default Devanagari to hi-IN
# (Sarvam's Hindi voice handles Marathi text comprehensibly).
_SCRIPT_TO_LANG = {
    "devanagari": "hi-IN",
    "bengali": "bn-IN",
    "gurmukhi": "pa-IN",
    "gujarati": "gu-IN",
    "odia": "od-IN",
    "tamil": "ta-IN",
    "telugu": "te-IN",
    "kannada": "kn-IN",
    "malayalam": "ml-IN",
}


def detect_language_code(text: str, default: str = "hi-IN") -> str:
    """Detect Sarvam ``target_language_code`` from text script.

    Counts characters in each Indic Unicode block, picks the dominant
    script, returns the matching Sarvam language code. Falls back to
    ``default`` (hi-IN) when no Indic script is present (e.g. pure
    English replies) — Sarvam's hi-IN voice handles English-mixed
    text reasonably well, so en-IN isn't always the right fallback.

    Returns ``en-IN`` only when no Indic character is detected at all
    AND the text contains any Latin letters (so we're confident it's
    actually English, not just empty).
    """
    if not text:
        return default

    counts = {script: 0 for script, _, _ in _SCRIPT_RANGES}
    has_latin = False
    for ch in text:
        code = ord(ch)
        if 0x0041 <= code <= 0x007A:  # A-Z / a-z (rough)
            has_latin = True
            continue
        for script, start, end in _SCRIPT_RANGES:
            if start <= code <= end:
                counts[script] += 1
                break

    total_indic = sum(counts.values())
    if total_indic == 0:
        return "en-IN" if has_latin else default

    dominant = max(counts.items(), key=lambda kv: kv[1])[0]
    return _SCRIPT_TO_LANG[dominant]


def normalize_currency_for_sarvam(text: str) -> str:
    """Pre-TTS currency normalization for Sarvam's Hindi TTS.

    Sarvam's ``bulbul:v3`` Hindi TTS has no pronunciation for the ``₹``
    glyph or the English word "rupees" — it falls back to spelling them
    out letter-by-letter ("r u p e e s"). We convert to the Devanagari
    form ``रुपए`` before the text hits the API.

    Conversions applied (in order, so the more specific patterns win):

    * ``₹500-800`` → ``500 से 800 रुपए``
    * ``₹500``    → ``500 रुपए``
    * lone ``₹`` → ``रुपए`` (rare, but covers edge cases)
    * ``Rs. 500`` / ``Rs 500`` → ``रुपए 500``
    * ``rupees`` / ``Rupees`` / ``rupee`` → ``रुपए``

    Leaves all other text untouched (intentional — we only fix what
    breaks; we don't touch English words Sarvam pronounces correctly).
    """
    if not text:
        return text
    # Ranges first so we don't accidentally insert रुपए between the
    # low and high values.
    text = re.sub(
        r"₹\s*(\d[\d,]*)\s*[-–—]\s*(\d[\d,]*)",
        r"\1 से \2 रुपए",
        text,
    )
    # Single amount with the ₹ prefix.
    text = re.sub(r"₹\s*(\d[\d,]*)", r"\1 रुपए", text)
    # Standalone glyph (no following digits).
    text = text.replace("₹", "रुपए ")
    # English "Rs." / "Rs " followed by a number.
    text = re.sub(r"\bRs\.?\s*(?=\d)", "रुपए ", text)
    # "rupees" / "rupee" as a word, in any case.
    text = re.sub(r"\brupees?\b", "रुपए", text, flags=re.IGNORECASE)
    return text


class SarvamTTS(BaseTTS):
    """
    Sarvam AI Text-to-Speech backend.

    Uses the Sarvam API for natural Hindi voice synthesis.
    Default voice is "manisha" for warm, conversational tone.
    """

    def __init__(self, config: Config):
        """
        Initialize Sarvam TTS.

        Args:
            config: Application configuration with API keys
        """
        self.config = config

        if not config.sarvam_api_key:
            raise RuntimeError("SARVAM_API_KEY missing. Set it in .env.")

    @property
    def voice_name(self) -> str:
        return f"sarvam:{self.config.sarvam_tts_voice}"

    def synthesize(self, text: str, output_path: Path) -> Dict[str, Any]:
        """
        Synthesize speech using Sarvam API (with retry).

        Args:
            text: Hindi text to convert to speech
            output_path: Path where WAV file should be saved

        Returns:
            Dictionary with audio_path and raw response
        """
        return retry_with_backoff(
            self._synthesize_once,
            text,
            output_path,
            max_attempts=3,
            base_delay=1.0,
            max_delay=10.0,
        )

    def _synthesize_once(self, text: str, output_path: Path) -> Dict[str, Any]:
        """Single attempt at Sarvam TTS API call."""
        headers = {
            "api-subscription-key": self.config.sarvam_api_key,
            "Content-Type": "application/json",
        }

        # Normalize ₹ / Rs / "rupees" → रुपए so Sarvam's Hindi TTS doesn't
        # spell them out letter-by-letter ("r u p e e s"). Note: this is
        # Hindi-script-specific; non-Devanagari languages don't go through
        # this path (Sarvam handles their currency words natively).
        detected_lang = detect_language_code(
            text, default=self.config.sarvam_tts_language
        )
        if detected_lang in ("hi-IN", "mr-IN"):
            text = normalize_currency_for_sarvam(text)

        payload: dict = {
            "text": text,
            "target_language_code": detected_lang,
            "speaker": self.config.sarvam_tts_voice,
            "model": self.config.sarvam_tts_model,
        }

        if self.config.sarvam_tts_sample_rate:
            payload["speech_sample_rate"] = self.config.sarvam_tts_sample_rate

        response = requests.post(
            self.config.sarvam_tts_url,
            headers=headers,
            json=payload,
            timeout=120,
        )

        if response.status_code >= 400:
            raise RuntimeError(
                f"Sarvam TTS error {response.status_code}: {response.text}"
            )

        # Handle direct audio response
        content_type = response.headers.get("Content-Type", "")
        if "audio" in content_type or response.content[:4] == b"RIFF":
            output_path.write_bytes(response.content)
            return {"audio_path": output_path, "raw": None}

        # Handle JSON response with base64 audio
        payload_json = response.json()
        audio_b64 = None

        if isinstance(payload_json, dict):
            audio_b64 = (
                payload_json.get("audio") or payload_json.get("audios", [None])[0]
            )

        if not audio_b64:
            raise RuntimeError(f"Sarvam TTS response missing audio: {payload_json}")

        output_path.write_bytes(base64.b64decode(audio_b64))
        return {"audio_path": output_path, "raw": payload_json}
