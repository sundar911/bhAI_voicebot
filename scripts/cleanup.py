"""
Data retention cleanup script for bhAI voice bot.

Deletes TTS outbound audio files older than 24 hours.
Run via cron or manually: python scripts/cleanup.py

Inbound audio and conversation data are kept indefinitely
(encrypted in SQLite and on disk).
"""

import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIO_SERVE_DIR = ROOT / "inference" / "outputs" / "twilio_audio"

# TTS outbound audio: delete after 24 hours
TTS_MAX_AGE_SECONDS = 24 * 60 * 60


def cleanup_tts_audio():
    """Delete TTS response audio files older than 24 hours."""
    if not AUDIO_SERVE_DIR.exists():
        print("No twilio_audio directory found, nothing to clean.")
        return

    now = time.time()
    deleted = 0

    for f in AUDIO_SERVE_DIR.iterdir():
        if f.is_file() and f.suffix in (".ogg", ".wav", ".mp3"):
            age = now - f.stat().st_mtime
            if age > TTS_MAX_AGE_SECONDS:
                f.unlink()
                deleted += 1

    print(f"Cleaned up {deleted} TTS audio file(s) older than 24h.")


if __name__ == "__main__":
    cleanup_tts_audio()
