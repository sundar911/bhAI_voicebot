from pathlib import Path
from typing import Any, Dict

import requests

from .audio_utils import convert_to_16k_mono, ensure_dir
from .config import Config


class SarvamSTT:
    def __init__(self, config: Config, work_dir: Path):
        self.config = config
        self.work_dir = work_dir
        ensure_dir(self.work_dir)

    def transcribe(self, input_audio: Path) -> Dict[str, Any]:
        if not input_audio.exists():
            raise FileNotFoundError(f"Audio not found: {input_audio}")

        wav_path = convert_to_16k_mono(input_audio, self.work_dir, self.config.sample_rate)

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
            raise RuntimeError(f"Sarvam STT error {response.status_code}: {response.text}")

        payload = response.json()
        text = (
            payload.get("text")
            or payload.get("transcript")
            or payload.get("transcription")
            or payload.get("output")
            or ""
        )
        return {"text": str(text).strip(), "raw": payload, "wav_path": wav_path}

