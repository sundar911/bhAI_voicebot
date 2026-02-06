#!/usr/bin/env python3
"""
Generate initial STT transcriptions for audio files.
Creates first-pass transcriptions using the specified STT model.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Add src to path for imports
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bhai.config import load_config, DATA_DIR
from src.bhai.stt.sarvam_stt import SarvamSTT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate initial STT transcriptions for audio files"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Input directory containing audio files (e.g., data/sharepoint_sync/hr_admin/)"
    )
    parser.add_argument(
        "--output",
        help="Output JSONL file (default: data/transcription_dataset/<domain>/transcriptions.jsonl)"
    )
    parser.add_argument(
        "--domain",
        default="hr_admin",
        choices=["hr_admin", "helpdesk", "production"],
        help="Domain for the transcriptions"
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to existing file instead of overwriting"
    )
    return parser.parse_args()


def get_audio_files(directory: Path) -> list[Path]:
    """Get all audio files from directory."""
    extensions = [".ogg", ".wav", ".mp3", ".m4a", ".opus"]
    files = []
    for ext in extensions:
        files.extend(directory.glob(f"**/*{ext}"))
    return sorted(files)


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input)

    if not input_dir.exists():
        print(f"Error: Input directory not found: {input_dir}")
        sys.exit(1)

    # Setup output file
    if args.output:
        output_file = Path(args.output)
    else:
        output_file = DATA_DIR / "transcription_dataset" / args.domain / "transcriptions.jsonl"

    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Load existing entries if appending
    existing_files = set()
    if args.append and output_file.exists():
        with open(output_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    existing_files.add(entry.get("audio_file", ""))

    # Get audio files
    audio_files = get_audio_files(input_dir)
    print(f"Found {len(audio_files)} audio files in {input_dir}")

    # Filter out already processed files
    new_files = [f for f in audio_files if f.name not in existing_files]
    print(f"Processing {len(new_files)} new files")

    if not new_files:
        print("No new files to process.")
        return

    # Initialize STT
    config = load_config()
    work_dir = ROOT / ".bhai_temp" / "stt_batch"
    work_dir.mkdir(parents=True, exist_ok=True)
    stt = SarvamSTT(config, work_dir=work_dir)

    # Process files
    mode = "a" if args.append else "w"
    with open(output_file, mode, encoding="utf-8") as f:
        for i, audio_path in enumerate(new_files):
            print(f"[{i+1}/{len(new_files)}] Processing: {audio_path.name}")

            try:
                result = stt.transcribe(audio_path)
                transcript = result["text"]

                entry = {
                    "audio_file": f"{args.domain}/{audio_path.name}",
                    "stt_model": stt.model_name,
                    "stt_draft": transcript,
                    "human_reviewed": None,
                    "final": None,
                    "status": "pending_review",
                    "reviewer": None,
                    "timestamp": datetime.now().isoformat()
                }

                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                print(f"    -> {transcript[:50]}...")

            except Exception as e:
                print(f"    Error: {e}")
                # Write error entry
                entry = {
                    "audio_file": f"{args.domain}/{audio_path.name}",
                    "stt_model": stt.model_name,
                    "stt_draft": None,
                    "human_reviewed": None,
                    "final": None,
                    "status": "error",
                    "error": str(e),
                    "reviewer": None,
                    "timestamp": datetime.now().isoformat()
                }
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"\nOutput written to: {output_file}")


if __name__ == "__main__":
    main()
