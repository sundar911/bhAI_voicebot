#!/usr/bin/env python3
"""
Error analysis: waterfall breakdown of WER per model.

Shows how much WER is attributable to each normalization layer:
  Raw WER  →  (−punct)  →  (−numbers)  →  (−diacritics)  →  nWER

This reveals each model's "error fingerprint": e.g. Saaras v3 has high
punctuation delta but low genuine errors; hallucinating models have high
genuine errors regardless of normalization.

Usage:
    python benchmarking/scripts/error_analysis.py --domain helpdesk
    python benchmarking/scripts/error_analysis.py --domain hr_admin --output benchmarking/results/error_analysis_hr_admin.csv
"""

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarking.scripts.compute_wer import compute_wer
from benchmarking.scripts.load_ground_truth import load_ground_truth
from benchmarking.scripts.normalize_indic import (
    collapse_whitespace,
    normalize_hindi,
    normalize_numbers,
    normalize_unicode,
    strip_punctuation,
)
from src.bhai.config import DATA_DIR


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Waterfall error breakdown per STT model"
    )
    parser.add_argument(
        "--domain", required=True,
        help="Domain to analyze (e.g. hr_admin, helpdesk, production)",
    )
    parser.add_argument(
        "--output",
        help="Optional CSV output path",
    )
    parser.add_argument(
        "--xlsx",
        help="Path to ground-truth xlsx",
    )
    return parser.parse_args()


def load_model_transcriptions(domain: str) -> dict[str, dict[str, str]]:
    """Load transcriptions from all per-model JSONL files for a domain."""
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


# ---------------------------------------------------------------------------
# Incremental normalization stages
# ---------------------------------------------------------------------------

def stage_raw(text: str) -> str:
    """No normalization."""
    return text


def stage_punct(text: str) -> str:
    """Strip punctuation only."""
    return collapse_whitespace(strip_punctuation(text))


def stage_numbers(text: str) -> str:
    """Strip punctuation + normalize numbers."""
    text = strip_punctuation(text)
    text = normalize_numbers(text)
    return collapse_whitespace(text)


def stage_full(text: str) -> str:
    """Full normalization pipeline."""
    return normalize_hindi(text)


STAGES = [
    ("raw",        stage_raw),
    ("−punct",     stage_punct),
    ("−numbers",   stage_numbers),
    ("−diacritics (nWER)", stage_full),
]


def aggregate_wer(pairs: list[tuple[str, str]], norm_fn) -> float:
    """Compute aggregate WER after applying norm_fn to both sides."""
    total_errors, total_words = 0, 0
    for hyp, ref in pairs:
        _, errors, words = compute_wer(norm_fn(hyp), norm_fn(ref))
        total_errors += errors
        total_words += words
    return total_errors / total_words if total_words else 0.0


def main() -> None:
    args = parse_args()

    # Load ground truth
    xlsx_path = Path(args.xlsx) if args.xlsx else None
    ground_truth = load_ground_truth(xlsx_path)
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

    # Compute waterfall per model
    results = []

    for model_name, transcriptions in sorted(model_transcriptions.items()):
        pairs: list[tuple[str, str]] = []
        for audio_file, reference in domain_gt.items():
            hypothesis = transcriptions.get(audio_file)
            if hypothesis is not None:
                pairs.append((hypothesis, reference))

        if not pairs:
            continue

        row = {"model": model_name, "files": len(pairs)}
        stage_wers = []

        for stage_name, norm_fn in STAGES:
            wer = aggregate_wer(pairs, norm_fn)
            row[stage_name] = round(wer, 4)
            stage_wers.append(wer)

        # Compute deltas (how much each stage reduces WER)
        row["delta_punct"] = round(stage_wers[0] - stage_wers[1], 4)
        row["delta_numbers"] = round(stage_wers[1] - stage_wers[2], 4)
        row["delta_diacritics"] = round(stage_wers[2] - stage_wers[3], 4)
        row["genuine_errors"] = round(stage_wers[3], 4)

        results.append(row)

    if not results:
        print("No models had matching transcriptions.")
        return

    # Print waterfall table
    print(f"{'Model':<50} {'Files':>5}  {'Raw':>7}  {'-punct':>7}  {'-nums':>7}  {'nWER':>7}  | {'Δpunct':>7}  {'Δnums':>7}  {'Δdiac':>7}  {'genuine':>7}")
    print("-" * 130)

    for r in sorted(results, key=lambda x: x["−diacritics (nWER)"]):
        print(
            f"{r['model']:<50} {r['files']:>5}  "
            f"{r['raw']:>6.2%}  {r['−punct']:>6.2%}  {r['−numbers']:>6.2%}  {r['−diacritics (nWER)']:>6.2%}  | "
            f"{r['delta_punct']:>6.2%}  {r['delta_numbers']:>6.2%}  {r['delta_diacritics']:>6.2%}  {r['genuine_errors']:>6.2%}"
        )

    # Save CSV
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = list(results[0].keys())
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(sorted(results, key=lambda x: x["−diacritics (nWER)"]))
        print(f"\nCSV saved to: {output_path}")


if __name__ == "__main__":
    main()
