"""
Audio processing utilities for bhAI voice bot.
Handles format conversion and file management.
"""

import uuid
from pathlib import Path

from pydub import AudioSegment


def ensure_dir(path: Path) -> Path:
    """Create directory if it doesn't exist."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def convert_to_16k_mono(
    input_path: Path,
    target_dir: Path,
    target_sr: int = 16000
) -> Path:
    """
    Convert audio to 16kHz mono WAV for STT models.
    Supports wav/mp3/m4a/ogg via ffmpeg (pydub backend).

    Args:
        input_path: Path to input audio file
        target_dir: Directory to save converted file
        target_sr: Target sample rate (default 16000)

    Returns:
        Path to converted WAV file
    """
    ensure_dir(target_dir)
    output_path = target_dir / f"{input_path.stem}_16k.wav"

    audio = AudioSegment.from_file(input_path)
    audio = audio.set_frame_rate(target_sr).set_channels(1).set_sample_width(2)
    audio.export(output_path, format="wav")

    return output_path


def unique_run_dir(base_dir: Path) -> Path:
    """Create a unique run directory with UUID-based name."""
    run_dir = base_dir / uuid.uuid4().hex[:12]
    ensure_dir(run_dir)
    return run_dir
