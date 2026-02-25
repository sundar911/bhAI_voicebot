#!/usr/bin/env python3
"""
Compare STT models across raw and normalized WER/CER + SemDist.

Reports six metrics per model:
  raw_wer, raw_cer   — current metrics, no normalization (backward compat)
  nwer, ncer         — after Indic text normalization (fair comparison)
  semdist            — semantic distance via sentence embeddings

Default: evaluates across ALL domains combined.
Use --domain to restrict to a single domain.

Usage:
    python benchmarking/scripts/compare_models.py
    python benchmarking/scripts/compare_models.py --domain helpdesk
    python benchmarking/scripts/compare_models.py --output benchmarking/results/comparison.csv
"""

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarking.scripts.compute_wer import compute_cer, compute_semdist, compute_wer
from benchmarking.scripts.load_ground_truth import load_ground_truth
from benchmarking.scripts.normalize_indic import normalize_hindi
from src.bhai.config import DATA_DIR

TRANSCRIPTION_DIR = DATA_DIR / "transcription_dataset"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare STT models by WER/CER/SemDist")
    parser.add_argument(
        "--domain",
        default=None,
        help="Restrict to a single domain (e.g. helpdesk). Default: all domains.",
    )
    parser.add_argument(
        "--output",
        help="Optional CSV output path for comparison table",
    )
    parser.add_argument(
        "--xlsx",
        help="Path to ground-truth xlsx (default: source_of_truth_transcriptions.xlsx)",
    )
    return parser.parse_args()


def load_model_transcriptions(domain: str | None = None) -> dict[str, dict[str, str]]:
    """
    Load transcriptions from per-model JSONL files.

    Args:
        domain: If provided, load only from that domain's directory.
                If None, load from all domain directories.

    Returns {model_name: {audio_file: stt_draft}}.
    """
    if domain:
        dirs = [TRANSCRIPTION_DIR / domain]
    else:
        dirs = sorted(
            d for d in TRANSCRIPTION_DIR.iterdir()
            if d.is_dir()
        )

    models: dict[str, dict[str, str]] = {}

    for domain_dir in dirs:
        if not domain_dir.exists():
            continue
        for jsonl_path in sorted(domain_dir.glob("transcriptions*.jsonl")):
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    model = entry.get("stt_model", "unknown")
                    audio_file = entry.get("audio_file", "")
                    draft = entry.get("stt_draft")

                    if not audio_file or not draft:
                        continue

                    if model not in models:
                        models[model] = {}
                    models[model][audio_file] = draft

    return models


def _aggregate_wer_cer(
    pairs: list[tuple[str, str]],
) -> tuple[float, float, int, int]:
    """Compute aggregate WER and CER over a list of (hypothesis, reference) pairs."""
    tw_errors, tw_words, tc_errors, tc_chars = 0, 0, 0, 0
    for hyp, ref in pairs:
        _, we, ww = compute_wer(hyp, ref)
        _, ce, cc = compute_cer(hyp, ref)
        tw_errors += we
        tw_words += ww
        tc_errors += ce
        tc_chars += cc
    wer = tw_errors / tw_words if tw_words else 0
    cer = tc_errors / tc_chars if tc_chars else 0
    return wer, cer, tw_errors, tw_words


def main() -> None:
    args = parse_args()

    # Load ground truth
    xlsx_path = Path(args.xlsx) if args.xlsx else None
    ground_truth = load_ground_truth(xlsx_path)

    # Filter to requested domain (or keep all)
    if args.domain:
        domain_gt = {k: v for k, v in ground_truth.items() if k.startswith(f"{args.domain}/")}
        scope = args.domain
    else:
        domain_gt = ground_truth
        scope = "all domains"

    print(f"Ground truth entries ({scope}): {len(domain_gt)}")

    if not domain_gt:
        print("No ground truth found.")
        return

    # Load model transcriptions
    model_transcriptions = load_model_transcriptions(args.domain)
    print(f"Models found: {list(model_transcriptions.keys())}")
    print(f"Loading SemDist model...\n")

    if not model_transcriptions:
        print("No model transcription files found.")
        return

    # Compute per-model metrics
    results = []
    for model_name, transcriptions in sorted(model_transcriptions.items()):
        raw_pairs: list[tuple[str, str]] = []
        norm_pairs: list[tuple[str, str]] = []

        for audio_file, reference in domain_gt.items():
            hypothesis = transcriptions.get(audio_file)
            if hypothesis is None:
                continue

            raw_pairs.append((hypothesis, reference))
            norm_pairs.append((normalize_hindi(hypothesis), normalize_hindi(reference)))

        if not raw_pairs:
            continue

        matched = len(raw_pairs)
        raw_wer, raw_cer, _, _ = _aggregate_wer_cer(raw_pairs)
        nwer, ncer, _, _ = _aggregate_wer_cer(norm_pairs)

        total_sd = sum(compute_semdist(h, r) for h, r in norm_pairs)

        results.append({
            "model": model_name,
            "files": matched,
            "raw_wer": round(raw_wer, 4),
            "raw_cer": round(raw_cer, 4),
            "nwer": round(nwer, 4),
            "ncer": round(ncer, 4),
            "semdist": round(total_sd / matched, 4),
        })

    if not results:
        print("No models had matching transcriptions against ground truth.")
        return

    # Print comparison table — sorted by nWER (the fair metric)
    print(
        f"{'Model':<50} {'Files':>5}  {'Raw WER':>8}  {'Raw CER':>8}  "
        f"{'nWER':>8}  {'nCER':>8}  {'SemDist':>8}"
    )
    print("-" * 108)

    for r in sorted(results, key=lambda x: x["nwer"]):
        print(
            f"{r['model']:<50} {r['files']:>5}  "
            f"{r['raw_wer']:>7.2%}  {r['raw_cer']:>7.2%}  "
            f"{r['nwer']:>7.2%}  {r['ncer']:>7.2%}  "
            f"{r['semdist']:>8.4f}"
        )

    # Save CSV
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = list(results[0].keys())
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(sorted(results, key=lambda x: x["nwer"]))
        print(f"\nCSV saved to: {output_path}")


if __name__ == "__main__":
    main()
