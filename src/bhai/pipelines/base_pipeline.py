"""
Base pipeline for voice bot processing.
Orchestrates STT -> LLM -> TTS flow.
"""

import json
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional

from ..audio_utils import ensure_dir
from ..config import Config, INFERENCE_OUTPUTS_DIR
from ..stt.base import BaseSTT
from ..tts.base import BaseTTS
from ..llm.base import BaseLLM


class BasePipeline(ABC):
    """
    Abstract base class for voice processing pipelines.

    Subclasses should implement domain-specific initialization
    and configuration while inheriting the core processing flow.
    """

    def __init__(
        self,
        config: Config,
        stt: BaseSTT,
        llm: BaseLLM,
        tts: Optional[BaseTTS] = None,
        domain: str = "hr_admin"
    ):
        """
        Initialize pipeline with components.

        Args:
            config: Application configuration
            stt: Speech-to-text backend
            llm: Language model backend
            tts: Text-to-speech backend (optional)
            domain: Knowledge domain for LLM context
        """
        self.config = config
        self.stt = stt
        self.llm = llm
        self.tts = tts
        self.domain = domain

    @property
    @abstractmethod
    def name(self) -> str:
        """Return pipeline name for logging."""
        pass

    def run(
        self,
        audio_path: Path,
        out_dir: Optional[Path] = None,
        enable_tts: bool = True
    ) -> Dict[str, Any]:
        """
        Run the full voice processing pipeline.

        Args:
            audio_path: Path to input audio file
            out_dir: Output directory (auto-generated if None)
            enable_tts: Whether to generate TTS output

        Returns:
            Dictionary with transcript, response, escalate flag,
            output directory, and timing log
        """
        # Setup output directory
        if out_dir is None:
            out_dir = INFERENCE_OUTPUTS_DIR / f"run_{int(time.time())}"
        out_dir = Path(out_dir)
        ensure_dir(out_dir)

        timings: Dict[str, float] = {}

        # STT
        t0 = time.perf_counter()
        stt_result = self.stt.transcribe(Path(audio_path))
        timings["asr_seconds"] = round(time.perf_counter() - t0, 3)

        transcript_text = stt_result["text"]
        (out_dir / "transcript.txt").write_text(transcript_text, encoding="utf-8")

        # LLM
        t1 = time.perf_counter()
        llm_result = self.llm.generate(transcript_text, domain=self.domain)
        timings["llm_seconds"] = round(time.perf_counter() - t1, 3)

        response_text = llm_result["text"]
        (out_dir / "response.txt").write_text(response_text, encoding="utf-8")

        # TTS (optional)
        tts_path = None
        if enable_tts and self.tts and response_text:
            t2 = time.perf_counter()
            tts_result = self.tts.synthesize(response_text, out_dir / "response.wav")
            tts_path = tts_result.get("audio_path")
            timings["tts_seconds"] = round(time.perf_counter() - t2, 3)
        else:
            timings["tts_seconds"] = 0.0

        # Build log
        log = {
            "pipeline": self.name,
            "domain": self.domain,
            "input_audio": str(Path(audio_path).resolve()),
            "wav_used": str(stt_result.get("wav_path")),
            "transcript_file": str((out_dir / "transcript.txt").resolve()),
            "response_file": str((out_dir / "response.txt").resolve()),
            "response_audio_file": str(tts_path.resolve()) if tts_path else None,
            "models": {
                "stt": self.stt.model_name,
                "llm": self.llm.model_name,
                "tts": self.tts.voice_name if self.tts else None,
            },
            "timings_seconds": timings,
            "escalate": llm_result.get("escalate", False),
        }
        (out_dir / "log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")

        return {
            "transcript": transcript_text,
            "response": response_text,
            "escalate": llm_result.get("escalate", False),
            "out_dir": out_dir,
            "log": log,
        }
