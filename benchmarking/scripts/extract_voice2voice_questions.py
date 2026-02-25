#!/usr/bin/env python3
"""
Extract question-only audio files from Voice2Voice.zip into sharepoint_audio.zip.
Organises files into domain folders matching the benchmarking directory layout.
"""

import shutil
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VOICE2VOICE_ZIP = ROOT / "Voice2Voice.zip"
OUTPUT_ZIP = ROOT / "sharepoint_audio.zip"

# Map Voice2Voice folder names → benchmarking domain names
FOLDER_TO_DOMAIN = {
    "Grievance": "grievance",
    "Helpdesk": "helpdesk",
    "HR-Admin": "hr_admin",
    "NextGen": "nextgen",
    "Production": "production",
}

AUDIO_EXTS = {".ogg", ".wav", ".mp3", ".m4a", ".opus"}


def is_question_audio(name: str) -> bool:
    """Return True if the filename is a question audio file."""
    suffix = Path(name).suffix.lower()
    stem = Path(name).stem
    return suffix in AUDIO_EXTS and "_Q_" in stem


def main() -> None:
    if not VOICE2VOICE_ZIP.exists():
        print(f"Error: {VOICE2VOICE_ZIP} not found")
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Extract Voice2Voice.zip
        print(f"Extracting {VOICE2VOICE_ZIP.name}...")
        with zipfile.ZipFile(VOICE2VOICE_ZIP, "r") as zf:
            zf.extractall(tmp)

        v2v_root = tmp / "Voice2Voice"
        if not v2v_root.exists():
            print("Error: Voice2Voice/ folder not found inside zip")
            return

        # Collect question audio files
        collected = {}  # domain -> list of (src_path, filename)
        for folder_name, domain in FOLDER_TO_DOMAIN.items():
            folder = v2v_root / folder_name
            if not folder.exists():
                print(f"  Warning: folder {folder_name}/ not found, skipping")
                continue

            q_files = [f for f in folder.iterdir() if is_question_audio(f.name)]
            q_files.sort(key=lambda p: p.name)
            collected[domain] = [(f, f.name) for f in q_files]
            print(f"  {folder_name} -> {domain}/: {len(q_files)} question files")

        # Build sharepoint_audio.zip
        total = 0
        print(f"\nCreating {OUTPUT_ZIP.name}...")
        with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zout:
            for domain, files in sorted(collected.items()):
                for src_path, filename in files:
                    arcname = f"{domain}/{filename}"
                    zout.write(src_path, arcname)
                    total += 1

        print(f"\nDone! {total} question audio files -> {OUTPUT_ZIP.name}")
        for domain in sorted(collected):
            print(f"  {domain}/: {len(collected[domain])} files")


if __name__ == "__main__":
    main()
