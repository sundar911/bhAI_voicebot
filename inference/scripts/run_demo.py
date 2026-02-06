#!/usr/bin/env python3
"""
CLI demo runner for bhAI voice bot.
Processes a single audio file through the HR-Admin pipeline.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from rich import print

# Add src to path for imports
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bhai.pipelines.hr_admin_pipeline import HRAdminPipeline
from src.bhai.config import load_config, INFERENCE_OUTPUTS_DIR


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="bhAI voice bot demo - process audio through HR-Admin pipeline"
    )
    parser.add_argument(
        "--audio",
        required=True,
        help="Path to input audio file (.wav/.mp3/.m4a/.ogg)"
    )
    parser.add_argument(
        "--out_dir",
        help="Output directory. Defaults to inference/outputs/<timestamp>/"
    )
    parser.add_argument(
        "--openai_model",
        help="Override OpenAI model (default: from env or gpt-4o-mini)"
    )
    parser.add_argument(
        "--no_tts",
        action="store_true",
        help="Skip TTS stage (only transcript and text response)"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    audio_path = Path(args.audio)

    if not audio_path.exists():
        print(f"[red]Error: Audio file not found: {audio_path}[/red]")
        sys.exit(1)

    # Setup output directory
    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = INFERENCE_OUTPUTS_DIR / run_id

    # Load config and optionally override model
    config = load_config()
    if args.openai_model:
        config.openai_model = args.openai_model

    # Initialize and run pipeline
    print(f"\n[cyan]Processing:[/cyan] {audio_path}")
    print(f"[cyan]Output dir:[/cyan] {out_dir}")

    pipeline = HRAdminPipeline(config=config, enable_tts=not args.no_tts)
    result = pipeline.run(
        audio_path=audio_path,
        out_dir=out_dir,
        enable_tts=not args.no_tts
    )

    # Display results
    print("\n[bold green]--- bhAI Voice Bot Run Complete ---[/bold green]")
    print(f"\n[cyan]Transcript:[/cyan]\n{result['transcript']}")
    print(f"\n[cyan]Response:[/cyan]\n{result['response']}")
    print(f"\n[cyan]Escalate:[/cyan] {result['escalate']}")
    print(f"\n[cyan]Outputs saved to:[/cyan] {result['out_dir'].resolve()}")

    if not args.no_tts:
        audio_file = result['out_dir'] / 'response.wav'
        if audio_file.exists():
            print(f"[cyan]Audio file:[/cyan] {audio_file.resolve()}")

    print(f"[cyan]Log:[/cyan] {(result['out_dir'] / 'log.json').resolve()}")


if __name__ == "__main__":
    main()
