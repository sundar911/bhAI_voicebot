#!/usr/bin/env python3
"""
Compute Word Error Rate (WER) and Character Error Rate (CER) for transcriptions.
Compares STT drafts against human-reviewed ground truth.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Tuple

# Add src to path for imports
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bhai.config import DATA_DIR


def levenshtein_distance(s1: List[str], s2: List[str]) -> int:
    """Compute Levenshtein distance between two sequences."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def compute_wer(hypothesis: str, reference: str) -> Tuple[float, int, int]:
    """
    Compute Word Error Rate.

    Returns:
        (wer, errors, total_words)
    """
    hyp_words = hypothesis.strip().split()
    ref_words = reference.strip().split()

    if not ref_words:
        return 0.0 if not hyp_words else 1.0, len(hyp_words), 0

    distance = levenshtein_distance(hyp_words, ref_words)
    wer = distance / len(ref_words)
    return wer, distance, len(ref_words)


def compute_cer(hypothesis: str, reference: str) -> Tuple[float, int, int]:
    """
    Compute Character Error Rate.

    Returns:
        (cer, errors, total_chars)
    """
    hyp_chars = list(hypothesis.strip())
    ref_chars = list(reference.strip())

    if not ref_chars:
        return 0.0 if not hyp_chars else 1.0, len(hyp_chars), 0

    distance = levenshtein_distance(hyp_chars, ref_chars)
    cer = distance / len(ref_chars)
    return cer, distance, len(ref_chars)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute WER and CER for transcriptions"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Input JSONL file with transcriptions"
    )
    parser.add_argument(
        "--output",
        help="Output JSON file for results (optional)"
    )
    parser.add_argument(
        "--use-final",
        action="store_true",
        help="Use 'final' field instead of 'human_reviewed' as reference"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_file = Path(args.input)

    if not input_file.exists():
        print(f"Error: Input file not found: {input_file}")
        sys.exit(1)

    # Read transcriptions
    entries = []
    with open(input_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))

    print(f"Loaded {len(entries)} entries")

    # Filter to entries with both STT draft and reference
    ref_field = "final" if args.use_final else "human_reviewed"
    valid_entries = [
        e for e in entries
        if e.get("stt_draft") and e.get(ref_field)
    ]

    print(f"Found {len(valid_entries)} entries with both STT draft and {ref_field}")

    if not valid_entries:
        print("No valid entries for comparison.")
        return

    # Compute metrics
    total_wer_errors = 0
    total_wer_words = 0
    total_cer_errors = 0
    total_cer_chars = 0
    per_file_results = []

    for entry in valid_entries:
        hypothesis = entry["stt_draft"]
        reference = entry[ref_field]

        wer, wer_errors, wer_words = compute_wer(hypothesis, reference)
        cer, cer_errors, cer_chars = compute_cer(hypothesis, reference)

        total_wer_errors += wer_errors
        total_wer_words += wer_words
        total_cer_errors += cer_errors
        total_cer_chars += cer_chars

        per_file_results.append({
            "audio_file": entry["audio_file"],
            "wer": round(wer, 4),
            "cer": round(cer, 4),
            "wer_errors": wer_errors,
            "cer_errors": cer_errors,
            "hypothesis": hypothesis,
            "reference": reference
        })

    # Compute overall metrics
    overall_wer = total_wer_errors / total_wer_words if total_wer_words > 0 else 0
    overall_cer = total_cer_errors / total_cer_chars if total_cer_chars > 0 else 0

    print("\n" + "=" * 50)
    print("OVERALL RESULTS")
    print("=" * 50)
    print(f"Files evaluated:    {len(valid_entries)}")
    print(f"Total words:        {total_wer_words}")
    print(f"Total characters:   {total_cer_chars}")
    print(f"")
    print(f"Word Error Rate:    {overall_wer:.2%} ({total_wer_errors} errors)")
    print(f"Char Error Rate:    {overall_cer:.2%} ({total_cer_errors} errors)")
    print("=" * 50)

    # Show worst performing files
    print("\nWorst performing files (by WER):")
    sorted_results = sorted(per_file_results, key=lambda x: x["wer"], reverse=True)
    for result in sorted_results[:5]:
        print(f"  {result['audio_file']}: WER={result['wer']:.2%}, CER={result['cer']:.2%}")

    # Save results if output specified
    if args.output:
        output_file = Path(args.output)
        results = {
            "summary": {
                "files_evaluated": len(valid_entries),
                "total_words": total_wer_words,
                "total_chars": total_cer_chars,
                "overall_wer": round(overall_wer, 4),
                "overall_cer": round(overall_cer, 4),
                "wer_errors": total_wer_errors,
                "cer_errors": total_cer_errors
            },
            "per_file": per_file_results
        }
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\nDetailed results saved to: {output_file}")


if __name__ == "__main__":
    main()
