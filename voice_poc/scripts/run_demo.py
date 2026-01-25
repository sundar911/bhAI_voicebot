import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from rich import print

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pipeline import run_pipeline

# #region agent log
DEBUG_LOG_PATH = Path("/Users/sundarraghavanl/PycharmProjects/bhAI_voice_bot/.cursor/debug.log")


def _debug_log(location: str, message: str, data: dict, *, run_id: str, hypothesis_id: str) -> None:
    try:
        payload = {
            "sessionId": "debug-session",
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with DEBUG_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
    except Exception:
        pass
# #endregion


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hindi voice agent PoC (terminal).")
    parser.add_argument("--audio", required=True, help="Path to input audio (.wav/.mp3/.m4a).")
    parser.add_argument(
        "--out_dir",
        help="Output directory. Defaults to outputs/<timestamp>.",
    )
    parser.add_argument(
        "--openai_model",
        help="Optional OpenAI model override (else uses OPENAI_MODEL env or default).",
    )
    parser.add_argument(
        "--no_tts",
        action="store_true",
        help="Skip TTS stage (only transcript and text response).",
    )
    return parser.parse_args()


def main() -> None:
    # #region agent log
    _debug_log(
        "run_demo.py:main:entry",
        "Runner started",
        {
            "cwd": os.getcwd(),
            "has_sarvam_key": bool(os.getenv("SARVAM_API_KEY")),
            "env_sarvam_key_len": len(os.getenv("SARVAM_API_KEY", "")),
            "env_file_exists": (ROOT / ".env").exists(),
        },
        run_id="pre-fix",
        hypothesis_id="H3",
    )
    # #endregion
    args = parse_args()
    audio_path = Path(args.audio)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    # Sarvam is the only pipeline now; no provider switching.

    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path("outputs") / run_id

    result = run_pipeline(
        audio_path=audio_path,
        out_dir=out_dir,
        openai_model=args.openai_model,
        enable_tts=not args.no_tts,
    )

    print("\n[bold green]--- Voice Agent Run Complete ---[/bold green]")
    print(f"[cyan]Transcript:[/cyan] {result['transcript']}")
    print(f"[cyan]Response:[/cyan] {result['response']}")
    print(f"[cyan]Escalate:[/cyan] {result['escalate']}")
    print(f"[cyan]Outputs saved to:[/cyan] {result['out_dir'].resolve()}")
    if not args.no_tts:
        print(f"[cyan]Audio file:[/cyan] {(result['out_dir'] / 'response.wav').resolve()}")
    print(f"[cyan]Log:[/cyan] {(result['out_dir'] / 'log.json').resolve()}")


if __name__ == "__main__":
    main()

