"""Re-transcribe orphaned web_chat audio files in a time range.

Usage:
    uv run python scripts/recover_webchat.py "2026-04-05T10:50:00" "2026-04-05T11:00:00"
"""

import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from src.bhai.config import INFERENCE_OUTPUTS_DIR, load_config
from src.bhai.stt.sarvam_stt import SarvamSTT


def main():
    if len(sys.argv) != 3:
        print("Usage: recover_webchat.py <start_iso> <end_iso>")
        print('  e.g. "2026-04-05T10:50:00" "2026-04-05T11:00:00"')
        sys.exit(1)

    start = datetime.fromisoformat(sys.argv[1])
    end = datetime.fromisoformat(sys.argv[2])

    config = load_config()
    audio_dir = INFERENCE_OUTPUTS_DIR / "web_chat"
    work_dir = audio_dir / "_recovery_work"
    work_dir.mkdir(exist_ok=True)

    stt = SarvamSTT(config, work_dir=work_dir)

    files = sorted(
        [
            f
            for f in audio_dir.glob("*_inbound.webm")
            if start <= datetime.fromtimestamp(f.stat().st_mtime) <= end
        ],
        key=lambda f: f.stat().st_mtime,
    )

    print(f"Transcribing {len(files)} files in range {start} → {end}\n")
    for f in files:
        ts = datetime.fromtimestamp(f.stat().st_mtime).strftime("%H:%M:%S")
        size_kb = f.stat().st_size // 1024
        try:
            result = stt.transcribe(f)
            print(f"[{ts}] ({size_kb}K) {f.name}")
            print(f"        {result['text']}")
            print()
        except Exception as e:
            print(f"[{ts}] ({size_kb}K) {f.name} — STT failed: {e}")
            print()


if __name__ == "__main__":
    main()
