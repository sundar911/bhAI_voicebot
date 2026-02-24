"""
Base class for GPU-based (local HuggingFace) STT models.
Handles device selection, lazy model loading, audio preprocessing, and cleanup.
"""

import gc
from abc import abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional

from ..audio_utils import convert_to_16k_mono, ensure_dir
from .base import BaseSTT


class GPUModelSTT(BaseSTT):
    """
    Abstract base for STT models that run locally on GPU via HuggingFace.

    Subclasses must implement:
        - _load_model()  — load weights into self._model / self._processor
        - transcribe()   — run inference
        - model_name     — property returning the HuggingFace model ID
    """

    def __init__(self, work_dir: Path, device: str = "auto", model_id: str = ""):
        self.work_dir = work_dir
        ensure_dir(self.work_dir)
        self.model_id = model_id
        self.device = self._resolve_device(device)
        self._model: Any = None
        self._processor: Any = None

    @staticmethod
    def _resolve_device(device: str) -> str:
        if device == "auto":
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        return device

    def _ensure_wav(self, audio_path: Path) -> Path:
        """Convert audio to 16 kHz mono WAV (reuses project utility)."""
        return convert_to_16k_mono(audio_path, self.work_dir)

    def _load_audio_tensor(self, wav_path: Path):
        """Load WAV as a float32 tensor. Returns (waveform, sample_rate)."""
        import torchaudio
        waveform, sr = torchaudio.load(str(wav_path))
        return waveform, sr

    @abstractmethod
    def _load_model(self) -> None:
        """Download / load model weights. Called lazily on first transcribe()."""
        pass

    def cleanup(self) -> None:
        """Unload model from GPU and free VRAM."""
        import torch
        self._model = None
        self._processor = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()
