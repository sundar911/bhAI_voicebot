"""
Sarvam AI TTS backend implementation.
Uses Sarvam's TTS API for natural Hindi speech synthesis.
"""

import base64
from pathlib import Path
from typing import Any, Dict

import requests

from ..config import Config
from .base import BaseTTS


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
        Synthesize speech using Sarvam API.

        Args:
            text: Hindi text to convert to speech
            output_path: Path where WAV file should be saved

        Returns:
            Dictionary with audio_path and raw response
        """
        headers = {
            "api-subscription-key": self.config.sarvam_api_key,
            "Content-Type": "application/json",
        }

        payload = {
            "inputs": [text],
            "target_language_code": self.config.sarvam_tts_language,
            "speaker": self.config.sarvam_tts_voice,
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
                payload_json.get("audio")
                or payload_json.get("audios", [None])[0]
            )

        if not audio_b64:
            raise RuntimeError(
                f"Sarvam TTS response missing audio: {payload_json}"
            )

        output_path.write_bytes(base64.b64decode(audio_b64))
        return {"audio_path": output_path, "raw": payload_json}
