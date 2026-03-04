"""
Sarvam AI STT backend implementation.
Uses Sarvam's saarika model for Hindi/Indic language transcription.
Handles audio > 30s via silence-aware chunking.
"""

from pathlib import Path
from typing import Any, Dict, List

import requests
from pydub import AudioSegment
from pydub.silence import split_on_silence

from ..audio_utils import convert_to_16k_mono, ensure_dir
from ..config import Config
from .base import BaseSTT

# Sarvam REST API hard limit
MAX_DURATION_S = 30
# Target chunk size (with headroom below the 30s limit)
TARGET_CHUNK_S = 28
# Overlap for fallback fixed-interval splitting (seconds)
OVERLAP_S = 3


class SarvamSTT(BaseSTT):
    """
    Sarvam AI Speech-to-Text backend.

    Uses the Sarvam API with saarika model for high-quality
    Hindi, Marathi, and Indic language transcription.
    Handles audio > 30s via silence-aware chunking.
    """

    def __init__(self, config: Config, work_dir: Path):
        self.config = config
        self.work_dir = work_dir
        ensure_dir(self.work_dir)

        if not config.sarvam_api_key:
            raise RuntimeError("SARVAM_API_KEY missing. Set it in .env.")

    @property
    def model_name(self) -> str:
        return self.config.sarvam_stt_model

    def transcribe(self, audio_path: Path) -> Dict[str, Any]:
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio not found: {audio_path}")

        wav_path = convert_to_16k_mono(
            audio_path, self.work_dir, self.config.sample_rate
        )
        audio = AudioSegment.from_file(wav_path)
        duration_s = len(audio) / 1000.0

        if duration_s <= MAX_DURATION_S:
            payload = self._call_api(wav_path)
        else:
            chunks = self._chunk_audio(audio)
            transcripts: List[str] = []
            for i, chunk in enumerate(chunks):
                chunk_path = self.work_dir / f"chunk_{i}.wav"
                chunk.export(chunk_path, format="wav")
                try:
                    payload = self._call_api(chunk_path)
                    text = self._extract_text(payload)
                    if text:
                        transcripts.append(text)
                finally:
                    chunk_path.unlink(missing_ok=True)

            full_text = " ".join(transcripts)
            payload = {"transcript": full_text, "_chunked": True, "_num_chunks": len(chunks)}

        text = self._extract_text(payload)
        return {
            "text": str(text).strip(),
            "raw": payload,
            "wav_path": wav_path,
        }

    # ── chunking ─────────────────────────────────────────────────────────

    def _chunk_audio(self, audio: AudioSegment) -> List[AudioSegment]:
        """Split audio into chunks that each fit under MAX_DURATION_S."""
        segments = split_on_silence(
            audio,
            min_silence_len=300,
            silence_thresh=audio.dBFS - 16,
            keep_silence=150,
        )

        if not segments:
            return self._fixed_split(audio)

        chunks: List[AudioSegment] = []
        current = AudioSegment.empty()

        for seg in segments:
            combined_len = (len(current) + len(seg)) / 1000.0
            if combined_len <= TARGET_CHUNK_S:
                current += seg
            else:
                if len(current) > 0:
                    chunks.append(current)
                if len(seg) / 1000.0 > TARGET_CHUNK_S:
                    chunks.extend(self._fixed_split(seg))
                    current = AudioSegment.empty()
                else:
                    current = seg

        if len(current) > 0:
            chunks.append(current)

        return chunks

    def _fixed_split(self, audio: AudioSegment) -> List[AudioSegment]:
        """Fallback: split at fixed intervals with overlap."""
        chunk_ms = TARGET_CHUNK_S * 1000
        overlap_ms = OVERLAP_S * 1000
        step_ms = chunk_ms - overlap_ms

        chunks: List[AudioSegment] = []
        pos = 0
        while pos < len(audio):
            end = min(pos + chunk_ms, len(audio))
            chunks.append(audio[pos:end])
            pos += step_ms
        return chunks

    # ── API call ─────────────────────────────────────────────────────────

    def _call_api(self, wav_path: Path) -> dict:
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

        return response.json()

    @staticmethod
    def _extract_text(payload: dict) -> str:
        return (
            payload.get("text")
            or payload.get("transcript")
            or payload.get("transcription")
            or payload.get("output")
            or ""
        )
