import uuid
from pathlib import Path
from typing import Tuple

from pydub import AudioSegment


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def convert_to_16k_mono(input_path: Path, target_dir: Path, target_sr: int = 16000) -> Path:
    """
    Convert audio to 16kHz mono wav for Whisper.
    Supports wav/mp3/m4a via ffmpeg (pydub backend).
    """
    ensure_dir(target_dir)
    output_path = target_dir / f"{input_path.stem}_16k.wav"
    audio = AudioSegment.from_file(input_path)
    audio = audio.set_frame_rate(target_sr).set_channels(1).set_sample_width(2)
    audio.export(output_path, format="wav")
    return output_path


def unique_run_dir(base_dir: Path) -> Path:
    run_dir = base_dir / uuid.uuid4().hex[:12]
    ensure_dir(run_dir)
    return run_dir

