#!/usr/bin/env python3
"""
Compare WER / CER across all STT models for a given domain.

Reads per-model JSONL files (transcriptions_{model}.jsonl) and compares
each model's stt_draft against the human-reviewed ground truth from the xlsx.

Usage:
    python benchmarking/scripts/compare_models.py --domain hr_admin
    python benchmarking/scripts/compare_models.py --domain helpdesk --output benchmarking/results/comparison.csv
"""

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarking.scripts.compute_wer import compute_cer, compute_wer
from benchmarking.scripts.load_ground_truth import load_ground_truth
from src.bhai.config import DATA_DIR


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare STT models by WER/CER")
    parser.add_argument(
        "--domain",
        required=True,
        help="Domain to compare (e.g. hr_admin, helpdesk, production)",
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


def load_model_transcriptions(domain: str) -> dict[str, dict[str, str]]:
    """
    Load transcriptions from all per-model JSONL files for a domain.

    Returns {model_name: {audio_file: stt_draft}}.
    Also loads the base transcriptions.jsonl (Sarvam) if present.
    """
    domain_dir = DATA_DIR / "transcription_dataset" / domain
    models: dict[str, dict[str, str]] = {}

    if not domain_dir.exists():
        return models

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


def main() -> None:
    args = parse_args()

    # Load ground truth
    xlsx_path = Path(args.xlsx) if args.xlsx else None
    ground_truth = load_ground_truth(xlsx_path)

    # Filter to requested domain
    domain_gt = {k: v for k, v in ground_truth.items() if k.startswith(f"{args.domain}/")}
    print(f"Ground truth entries for '{args.domain}': {len(domain_gt)}")

    if not domain_gt:
        print("No ground truth found for this domain.")
        return

    # Load model transcriptions
    model_transcriptions = load_model_transcriptions(args.domain)
    print(f"Models found: {list(model_transcriptions.keys())}\n")

    if not model_transcriptions:
        print("No model transcription files found.")
        return

    # Compute per-model metrics
    results = []
    for model_name, transcriptions in sorted(model_transcriptions.items()):
        total_wer_errors = 0
        total_wer_words = 0
        total_cer_errors = 0
        total_cer_chars = 0
        matched = 0

        for audio_file, reference in domain_gt.items():
            hypothesis = transcriptions.get(audio_file)
            if hypothesis is None:
                continue

            matched += 1
            wer, wer_errors, wer_words = compute_wer(hypothesis, reference)
            cer, cer_errors, cer_chars = compute_cer(hypothesis, reference)

            total_wer_errors += wer_errors
            total_wer_words += wer_words
            total_cer_errors += cer_errors
            total_cer_chars += cer_chars

        if matched == 0:
            continue

        overall_wer = total_wer_errors / total_wer_words if total_wer_words > 0 else 0
        overall_cer = total_cer_errors / total_cer_chars if total_cer_chars > 0 else 0

        results.append({
            "model": model_name,
            "files_compared": matched,
            "wer": round(overall_wer, 4),
            "cer": round(overall_cer, 4),
            "wer_errors": total_wer_errors,
            "total_words": total_wer_words,
        })

    # Print comparison table
    print(f"{'Model':<50} {'Files':>5}  {'WER':>8}  {'CER':>8}")
    print("-" * 78)
    for r in sorted(results, key=lambda x: x["wer"]):
        print(
            f"{r['model']:<50} {r['files_compared']:>5}  "
            f"{r['wer']:>7.2%}  {r['cer']:>7.2%}"
        )

    # Save CSV
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(sorted(results, key=lambda x: x["wer"]))
        print(f"\nCSV saved to: {output_path}")


if __name__ == "__main__":
    main()
