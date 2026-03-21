"""
ElevenLabs TTS backend implementation.
Uses Vidhi's cloned voice with optional emotion audio tags.
Outputs OGG Opus for WhatsApp compatibility.
"""

import tempfile
from pathlib import Path
from typing import Any, Dict, List

from pydub import AudioSegment

from ..config import Config
from ..resilience.retry import retry_with_backoff
from .base import BaseTTS
from .emotion_tagger import annotate_with_emotions


class ElevenLabsTTS(BaseTTS):
    """
    ElevenLabs Text-to-Speech backend.

    Uses a cloned voice with per-segment emotion control via audio tags.
    Converts output to OGG Opus for WhatsApp delivery.
    """

    def __init__(self, config: Config):
        if not config.elevenlabs_api_key:
            raise RuntimeError("ELEVENLABS_API_KEY missing. Set it in .env.")
        if not config.elevenlabs_voice_id:
            raise RuntimeError("ELEVENLABS_VOICE_ID missing. Set it in .env.")

        self.config = config

        from elevenlabs import ElevenLabs

        self._client = ElevenLabs(api_key=config.elevenlabs_api_key)

    @property
    def voice_name(self) -> str:
        return f"elevenlabs:{self.config.elevenlabs_voice_id}"

    def synthesize(self, text: str, output_path: Path) -> Dict[str, Any]:
        """
        Synthesize speech from text (with retry). May contain ElevenLabs audio tags.

        Output is always OGG Opus regardless of output_path extension.
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
        """Single attempt at ElevenLabs TTS API call."""
        from elevenlabs import VoiceSettings

        audio_iterator = self._client.text_to_speech.convert(
            voice_id=self.config.elevenlabs_voice_id,
            text=text,
            model_id=self.config.elevenlabs_model_id,
            voice_settings=VoiceSettings(
                stability=self.config.elevenlabs_stability,
                similarity_boost=self.config.elevenlabs_similarity_boost,
                style=self.config.elevenlabs_style,
                use_speaker_boost=True,
            ),
            output_format="mp3_44100_128",
        )

        # Collect streamed audio bytes
        audio_bytes = b"".join(audio_iterator)

        # Convert MP3 → OGG Opus via pydub
        output_path = Path(output_path)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as tmp:
            tmp.write(audio_bytes)
            tmp.flush()
            audio = AudioSegment.from_mp3(tmp.name)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        audio.export(str(output_path), format="ogg", codec="libopus")

        return {"audio_path": output_path, "raw": None}

    def synthesize_with_emotions(
        self, segments: List[dict], output_path: Path
    ) -> Dict[str, Any]:
        """
        Synthesize speech from emotion-annotated segments.

        Converts segments to tagged text via annotate_with_emotions(),
        then calls synthesize().
        """
        tagged_text = annotate_with_emotions(segments)
        return self.synthesize(tagged_text, output_path)
