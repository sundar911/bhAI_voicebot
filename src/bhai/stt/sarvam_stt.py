"""
Sarvam AI STT backend implementation.
Uses Sarvam's saarika model for Hindi/Indic language transcription.
"""

from pathlib import Path
from typing import Any, Dict

import requests

from ..audio_utils import convert_to_16k_mono, ensure_dir
from ..config import Config
from .base import BaseSTT


class SarvamSTT(BaseSTT):
    """
    Sarvam AI Speech-to-Text backend.

    Uses the Sarvam API with saarika model for high-quality
    Hindi, Marathi, and Indic language transcription.
    """

    def __init__(self, config: Config, work_dir: Path):
        """
        Initialize Sarvam STT.

        Args:
            config: Application configuration with API keys
            work_dir: Directory for temporary files
        """
        self.config = config
        self.work_dir = work_dir
        ensure_dir(self.work_dir)

        if not config.sarvam_api_key:
            raise RuntimeError("SARVAM_API_KEY missing. Set it in .env.")

    @property
    def model_name(self) -> str:
        return self.config.sarvam_stt_model

    def transcribe(self, audio_path: Path) -> Dict[str, Any]:
        """
        Transcribe audio using Sarvam API.

        Args:
            audio_path: Path to input audio file

        Returns:
            Dictionary with text, raw response, and wav_path
        """
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio not found: {audio_path}")

        # Convert to 16kHz mono WAV
        wav_path = convert_to_16k_mono(
            audio_path, self.work_dir, self.config.sample_rate
        )

        headers = {
            "api-subscription-key": self.config.sarvam_api_key,
        }
        data = {
            "model": self.config.sarvam_stt_model,
        }

        with wav_path.open("rb") as f:
            files = {
                "file": (wav_path.name, f, "audio/wav"),
            }
            response = requests.post(
                self.config.sarvam_stt_url,
                headers=headers,
                data=data,
                files=files,
                timeout=120,
            )

        if response.status_code >= 400:
            raise RuntimeError(
                f"Sarvam STT error {response.status_code}: {response.text}"
            )

        payload = response.json()

        # Handle various response formats
        text = (
            payload.get("text")
            or payload.get("transcript")
            or payload.get("transcription")
            or payload.get("output")
            or ""
        )

        return {
            "text": str(text).strip(),
            "raw": payload,
            "wav_path": wav_path,
        }
