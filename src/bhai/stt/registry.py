"""
Model registry for STT backends.
Uses lazy imports so torch/transformers are not loaded until a model is requested.
"""

import importlib
from pathlib import Path
from typing import Any

from .base import BaseSTT

# name -> (module_path, class_name)
_REGISTRY: dict[str, tuple[str, str]] = {
    "sarvam_saarika":  ("src.bhai.stt.sarvam_stt",      "SarvamSTT"),
    "indic_whisper":   ("src.bhai.stt.indic_whisper",    "IndicWhisperSTT"),
    "vaani_whisper":   ("src.bhai.stt.vaani_whisper",    "VaaniWhisperSTT"),
    "indic_conformer": ("src.bhai.stt.indic_conformer",  "IndicConformerSTT"),
    "whisper_large_v3":("src.bhai.stt.whisper_large_v3", "WhisperLargeV3STT"),
    "meta_mms":        ("src.bhai.stt.meta_mms",         "MetaMmsSTT"),
    "indic_wav2vec":   ("src.bhai.stt.indic_wav2vec",    "IndicWav2VecSTT"),
}


def list_models() -> list[str]:
    """Return all registered model names."""
    return list(_REGISTRY.keys())


def get_stt(name: str, work_dir: Path, **kwargs: Any) -> BaseSTT:
    """
    Instantiate an STT model by its registry name.

    Args:
        name:     Key from the registry (e.g. "indic_whisper").
        work_dir: Scratch directory for temporary WAV files.
        **kwargs: Forwarded to the model constructor (device, config, etc.).
    """
    if name not in _REGISTRY:
        raise ValueError(f"Unknown model '{name}'. Available: {list_models()}")

    module_path, class_name = _REGISTRY[name]
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    return cls(work_dir=work_dir, **kwargs)
