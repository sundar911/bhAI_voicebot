#!/usr/bin/env python3
"""Smoke-test the REAL cot/out contract against a live LLM backend.

Unlike the unit tests (which mock _call_api), this makes an ACTUAL API call so
you can verify that the live model obeys the {"cot", "out"} contract:
native JSON enforcement holds, the parser extracts "out", and reasoning never
leaks into the delivered text.

Requires real API keys in .env (ANTHROPIC_API_KEY / SARVAM_API_KEY /
OPENAI_API_KEY depending on the backend).

Usage:
    uv run python scripts/smoke_llm.py                      # backend from .env
    uv run python scripts/smoke_llm.py --backend claude
    uv run python scripts/smoke_llm.py --backend sarvam
    uv run python scripts/smoke_llm.py --backend openai
    uv run python scripts/smoke_llm.py --emotions          # generate_with_emotions
    uv run python scripts/smoke_llm.py --transcript "bhai meri tabiyat thik nahi"
    uv run python scripts/smoke_llm.py --all               # try every keyed backend
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bhai.config import load_config  # noqa: E402
from src.bhai.llm import create_llm  # noqa: E402

DEFAULT_TRANSCRIPT = "अरे भाई, आज बहुत थकान है। थोड़ी बात करते हैं?"

# Which env key each backend needs — used by --all to skip unkeyed backends.
_BACKEND_KEY = {
    "claude": "anthropic_api_key",
    "sarvam": "sarvam_api_key",
    "openai": "openai_api_key",
}


def run_once(backend: str | None, transcript: str, use_emotions: bool) -> bool:
    """Run one real call. Returns True if the contract held, False otherwise."""
    cfg = load_config()
    if backend:
        cfg.llm_backend = backend

    print("=" * 70)
    print(f"backend = {cfg.llm_backend}")

    try:
        llm = create_llm(cfg)
    except Exception as e:  # missing key, bad config, etc.
        print(f"  SKIP/ERROR creating LLM: {e}")
        return False

    print(f"model   = {llm.model_name}")
    print(f"prompt  = {transcript!r}")
    print(f"method  = {'generate_with_emotions' if use_emotions else 'generate'}")

    fn = llm.generate_with_emotions if use_emotions else llm.generate
    try:
        result = fn(transcript)
    except Exception as e:
        print(f"  API CALL FAILED: {e}")
        return False

    out = result.get("text", "")
    cot = result.get("cot", "")
    parsed = result.get("parsed")
    raw = result.get("raw", "")

    print(f"\nparsed  = {parsed}")
    print(f"\n--- out (delivered to user) ---\n{out}")
    print(f"\n--- cot (private, never delivered) ---\n{cot or '(empty)'}")
    print(f"\n--- raw (first 800 chars) ---\n{raw[:800]}")

    # Contract checks
    ok = True
    if not out:
        print("\n[FAIL] out is empty")
        ok = False
    if parsed is False:
        print("\n[WARN] parsed=False — model output could not be parsed, "
              "fell back to the canned line")
        ok = False
    if cot and cot.strip() and cot.strip() in out:
        print("\n[FAIL] COT LEAKED — cot text appears inside out!")
        ok = False
    for marker in ("cot", "EMOTIONS_JSON", "ESCALATE", "system prompt"):
        if marker.lower() in out.lower():
            print(f"\n[WARN] suspicious marker {marker!r} present in out")

    print(f"\n==> {'OK ✓' if ok else 'PROBLEM ✗'}")
    return ok


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--backend",
        choices=["claude", "sarvam", "openai"],
        help="Override LLM_BACKEND for this run (default: value from .env)",
    )
    ap.add_argument("--transcript", default=DEFAULT_TRANSCRIPT)
    ap.add_argument(
        "--emotions",
        action="store_true",
        help="Use generate_with_emotions() instead of generate()",
    )
    ap.add_argument(
        "--all",
        action="store_true",
        help="Try every backend that has an API key configured",
    )
    args = ap.parse_args()

    if args.all:
        cfg = load_config()
        results = {}
        for backend, key_attr in _BACKEND_KEY.items():
            if not getattr(cfg, key_attr, ""):
                print(f"(skipping {backend}: no API key set)")
                continue
            results[backend] = run_once(backend, args.transcript, args.emotions)
            print()
        print("=" * 70)
        print("SUMMARY:", {b: ("OK" if ok else "PROBLEM") for b, ok in results.items()})
        sys.exit(0 if results and all(results.values()) else 1)

    ok = run_once(args.backend, args.transcript, args.emotions)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
