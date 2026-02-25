#!/usr/bin/env python3
"""
Generate initial STT transcriptions for audio files.
Supports any registered STT model via --model flag.

Usage:
    # Single model
    python benchmarking/scripts/generate_initial_transcriptions.py \
        --model indic_whisper --input data/sharepoint_sync/hr_admin/ --domain hr_admin

    # All GPU models
    python benchmarking/scripts/generate_initial_transcriptions.py \
        --model all --input data/sharepoint_sync/hr_admin/ --domain hr_admin --device cuda
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# Add src to path for imports
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bhai.config import DATA_DIR
from src.bhai.stt.registry import get_stt, list_models


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate initial STT transcriptions for audio files"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Input directory containing audio files",
    )
    parser.add_argument(
        "--output",
        help="Output JSONL file (default: data/transcription_dataset/<domain>/transcriptions_<model>.jsonl)",
    )
    parser.add_argument(
        "--domain",
        default="hr_admin",
        help="Domain for the transcriptions",
    )
    parser.add_argument(
        "--model",
        default="sarvam_saarika",
        help=f"Model registry name or 'all'. Available: {list_models()}",
    )
    parser.add_argument(
        "--device",
        default="auto",
        help="Device: auto, cuda, cpu (default: auto)",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to existing file instead of overwriting",
    )
    return parser.parse_args()


def get_audio_files(directory: Path) -> list[Path]:
    """Get all audio files from directory."""
    extensions = [".ogg", ".wav", ".mp3", ".m4a", ".opus"]
    files = []
    for ext in extensions:
        files.extend(directory.glob(f"**/*{ext}"))
    return sorted(files)


def run_model(
    model_name: str,
    audio_files: list[Path],
    domain: str,
    output_file: Path,
    device: str,
    append: bool,
) -> None:
    """Run a single model across all audio files."""
    work_dir = ROOT / ".bhai_temp" / f"stt_{model_name}"
    work_dir.mkdir(parents=True, exist_ok=True)

    # Build kwargs for the model constructor
    kwargs: dict = {}
    if model_name in ("sarvam_saarika", "sarvam_saaras"):
        from src.bhai.config import load_config
        kwargs["config"] = load_config()
    else:
        kwargs["device"] = device

    stt = get_stt(model_name, work_dir=work_dir, **kwargs)
    print(f"\n{'='*60}")
    print(f"Model: {stt.model_name}")
    print(f"Output: {output_file}")
    print(f"Files: {len(audio_files)}")
    print(f"{'='*60}\n")

    # Load existing entries if appending
    existing_files: set[str] = set()
    if append and output_file.exists():
        with open(output_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    existing_files.add(entry.get("audio_file", ""))

    new_files = [
        fp for fp in audio_files
        if f"{domain}/{fp.name}" not in existing_files
    ]
    print(f"Skipping {len(audio_files) - len(new_files)} already-processed files")
    print(f"Processing {len(new_files)} new files\n")

    if not new_files:
        print("Nothing to process.")
        return

    output_file.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"

    with open(output_file, mode, encoding="utf-8") as f:
        for i, audio_path in enumerate(new_files):
            print(f"[{i+1}/{len(new_files)}] {audio_path.name}", end=" ", flush=True)

            start = time.time()
            try:
                result = stt.transcribe(audio_path)
                elapsed = time.time() - start
                transcript = result["text"]

                entry = {
                    "audio_file": f"{domain}/{audio_path.name}",
                    "stt_model": stt.model_name,
                    "stt_draft": transcript,
                    "latency_seconds": round(elapsed, 2),
                    "human_reviewed": None,
                    "final": None,
                    "status": "pending_review",
                    "timestamp": datetime.now().isoformat(),
                }
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                f.flush()
                print(f"({elapsed:.1f}s) {transcript[:50]}...")

            except RuntimeError as e:
                elapsed = time.time() - start
                if "out of memory" in str(e).lower():
                    print(f"OOM after {elapsed:.1f}s — cleaning up")
                    stt.cleanup()
                    # Re-initialize for next file
                    stt = get_stt(model_name, work_dir=work_dir, **kwargs)
                    status = "oom_error"
                else:
                    print(f"Error: {e}")
                    status = "error"

                entry = {
                    "audio_file": f"{domain}/{audio_path.name}",
                    "stt_model": stt.model_name,
                    "stt_draft": None,
                    "latency_seconds": round(elapsed, 2),
                    "human_reviewed": None,
                    "final": None,
                    "status": status,
                    "error": str(e),
                    "timestamp": datetime.now().isoformat(),
                }
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                f.flush()

            except Exception as e:
                elapsed = time.time() - start
                print(f"Error ({elapsed:.1f}s): {e}")
                entry = {
                    "audio_file": f"{domain}/{audio_path.name}",
                    "stt_model": stt.model_name,
                    "stt_draft": None,
                    "latency_seconds": round(elapsed, 2),
                    "human_reviewed": None,
                    "final": None,
                    "status": "error",
                    "error": str(e),
                    "timestamp": datetime.now().isoformat(),
                }
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                f.flush()

    stt.cleanup()
    print(f"\nDone with {stt.model_name}. Output: {output_file}")


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input)

    if not input_dir.exists():
        print(f"Error: Input directory not found: {input_dir}")
        sys.exit(1)

    audio_files = get_audio_files(input_dir)
    print(f"Found {len(audio_files)} audio files in {input_dir}")

    if not audio_files:
        print("No audio files found.")
        return

    # Determine which models to run
    if args.model == "all":
        models_to_run = [m for m in list_models() if m != "sarvam_saarika"]
    else:
        models_to_run = [args.model]

    for model_name in models_to_run:
        if args.output:
            output_file = Path(args.output)
        else:
            safe_name = model_name.replace("/", "_")
            output_file = (
                DATA_DIR / "transcription_dataset" / args.domain
                / f"transcriptions_{safe_name}.jsonl"
            )

        run_model(
            model_name=model_name,
            audio_files=audio_files,
            domain=args.domain,
            output_file=output_file,
            device=args.device,
            append=args.append,
        )


if __name__ == "__main__":
    main()
