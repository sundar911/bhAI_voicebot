#!/usr/bin/env python3
"""
Compute Word Error Rate (WER), Character Error Rate (CER), and optional
Semantic Distance (SemDist) for STT transcriptions.

Compares STT drafts against human-reviewed ground truth, with optional
Indic text normalization for fair Hindi/Marathi ASR evaluation.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple

# Add src to path for imports
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bhai.config import DATA_DIR


# ---------------------------------------------------------------------------
# Levenshtein distance (core metric engine)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Semantic Distance (SemDist)
# ---------------------------------------------------------------------------

_semdist_model = None


def _get_semdist_model():
    """Lazy-load a multilingual sentence-transformer for SemDist."""
    global _semdist_model
    if _semdist_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _semdist_model = SentenceTransformer(
                "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
            )
        except ImportError:
            raise ImportError(
                "sentence-transformers is required for SemDist.\n"
                "Install: pip install sentence-transformers"
            )
    return _semdist_model


def compute_semdist(hypothesis: str, reference: str) -> float:
    """
    Compute Semantic Distance: 1 - cosine_similarity(embed(hyp), embed(ref)).

    Returns a value in [0, 2] where 0 = identical meaning, higher = more different.
    """
    import numpy as np

    model = _get_semdist_model()
    embeddings = model.encode([hypothesis, reference])
    cos_sim = np.dot(embeddings[0], embeddings[1]) / (
        np.linalg.norm(embeddings[0]) * np.linalg.norm(embeddings[1])
    )
    return float(1 - cos_sim)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

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
    parser.add_argument(
        "--normalize",
        action="store_true",
        help="Apply Indic text normalization before computing metrics"
    )
    parser.add_argument(
        "--semdist",
        action="store_true",
        help="Also compute Semantic Distance (requires sentence-transformers)"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_file = Path(args.input)

    if not input_file.exists():
        print(f"Error: Input file not found: {input_file}")
        sys.exit(1)

    # Load normalizer if requested
    norm_fn: Optional[callable] = None
    if args.normalize:
        from benchmarking.scripts.normalize_indic import normalize_hindi
        norm_fn = normalize_hindi
        print("Using Indic text normalization")

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
    total_semdist = 0.0
    per_file_results = []

    for entry in valid_entries:
        hypothesis = entry["stt_draft"]
        reference = entry[ref_field]

        if norm_fn:
            hypothesis = norm_fn(hypothesis)
            reference = norm_fn(reference)

        wer, wer_errors, wer_words = compute_wer(hypothesis, reference)
        cer, cer_errors, cer_chars = compute_cer(hypothesis, reference)

        total_wer_errors += wer_errors
        total_wer_words += wer_words
        total_cer_errors += cer_errors
        total_cer_chars += cer_chars

        result = {
            "audio_file": entry["audio_file"],
            "wer": round(wer, 4),
            "cer": round(cer, 4),
            "wer_errors": wer_errors,
            "cer_errors": cer_errors,
            "hypothesis": hypothesis,
            "reference": reference,
        }

        if args.semdist:
            sd = compute_semdist(hypothesis, reference)
            total_semdist += sd
            result["semdist"] = round(sd, 4)

        per_file_results.append(result)

    # Compute overall metrics
    overall_wer = total_wer_errors / total_wer_words if total_wer_words > 0 else 0
    overall_cer = total_cer_errors / total_cer_chars if total_cer_chars > 0 else 0
    avg_semdist = total_semdist / len(valid_entries) if args.semdist else None

    label = "NORMALIZED " if args.normalize else ""
    print(f"\n{'=' * 50}")
    print(f"{label}OVERALL RESULTS")
    print(f"{'=' * 50}")
    print(f"Files evaluated:    {len(valid_entries)}")
    print(f"Total words:        {total_wer_words}")
    print(f"Total characters:   {total_cer_chars}")
    print()
    print(f"Word Error Rate:    {overall_wer:.2%} ({total_wer_errors} errors)")
    print(f"Char Error Rate:    {overall_cer:.2%} ({total_cer_errors} errors)")
    if avg_semdist is not None:
        print(f"Avg Semantic Dist:  {avg_semdist:.4f}")
    print("=" * 50)

    # Show worst performing files
    print("\nWorst performing files (by WER):")
    sorted_results = sorted(per_file_results, key=lambda x: x["wer"], reverse=True)
    for result in sorted_results[:5]:
        line = f"  {result['audio_file']}: WER={result['wer']:.2%}, CER={result['cer']:.2%}"
        if "semdist" in result:
            line += f", SemDist={result['semdist']:.4f}"
        print(line)

    # Save results if output specified
    if args.output:
        output_file = Path(args.output)
        summary = {
            "files_evaluated": len(valid_entries),
            "total_words": total_wer_words,
            "total_chars": total_cer_chars,
            "overall_wer": round(overall_wer, 4),
            "overall_cer": round(overall_cer, 4),
            "wer_errors": total_wer_errors,
            "cer_errors": total_cer_errors,
            "normalized": args.normalize,
        }
        if avg_semdist is not None:
            summary["avg_semdist"] = round(avg_semdist, 4)

        results = {
            "summary": summary,
            "per_file": per_file_results,
        }
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\nDetailed results saved to: {output_file}")


if __name__ == "__main__":
    main()
