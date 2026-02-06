#!/usr/bin/env python3
"""
Transcribe Q (question) files from all domains using Sarvam STT.
Only processes files matching *_Q_* pattern.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bhai.config import load_config, DATA_DIR
from src.bhai.stt.sarvam_stt import SarvamSTT


def get_question_files(directory: Path) -> list[Path]:
    """Get only Q (question) files from directory."""
    files = []
    for pattern in ["*_Q_*.ogg", "*_Q_*.wav", "*_Q_*.mp3", "*_Q_*.m4a"]:
        files.extend(directory.glob(pattern))
    return sorted(files)


def main():
    config = load_config()
    work_dir = ROOT / ".bhai_temp" / "stt_batch"
    work_dir.mkdir(parents=True, exist_ok=True)
    stt = SarvamSTT(config, work_dir=work_dir)

    domains = ["helpdesk", "hr_admin", "production"]

    for domain in domains:
        input_dir = DATA_DIR / "sharepoint_sync" / domain
        output_file = DATA_DIR / "transcription_dataset" / domain / "transcriptions.jsonl"
        output_file.parent.mkdir(parents=True, exist_ok=True)

        q_files = get_question_files(input_dir)
        print(f"\n=== {domain.upper()} ===")
        print(f"Found {len(q_files)} question files")

        if not q_files:
            print("No Q files found, skipping...")
            continue

        with open(output_file, "w", encoding="utf-8") as f:
            for i, audio_path in enumerate(q_files):
                print(f"[{i+1}/{len(q_files)}] {audio_path.name}", end=" -> ")

                try:
                    result = stt.transcribe(audio_path)
                    transcript = result["text"]
                    print(f"{transcript[:50]}..." if len(transcript) > 50 else transcript)

                    entry = {
                        "audio_file": f"{domain}/{audio_path.name}",
                        "stt_model": stt.model_name,
                        "stt_draft": transcript,
                        "human_reviewed": None,
                        "final": None,
                        "status": "pending_review",
                        "reviewer": None,
                        "timestamp": datetime.now().isoformat()
                    }
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")

                except Exception as e:
                    print(f"ERROR: {e}")
                    entry = {
                        "audio_file": f"{domain}/{audio_path.name}",
                        "stt_model": stt.model_name,
                        "stt_draft": None,
                        "error": str(e),
                        "status": "error",
                        "timestamp": datetime.now().isoformat()
                    }
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        print(f"Saved to: {output_file}")

    print("\n=== DONE ===")
    print("Next steps:")
    print("1. Review transcriptions in data/transcription_dataset/*/transcriptions.jsonl")
    print("2. TM team corrects errors in 'human_reviewed' field")
    print("3. Run compute_wer.py to measure accuracy")


if __name__ == "__main__":
    main()
