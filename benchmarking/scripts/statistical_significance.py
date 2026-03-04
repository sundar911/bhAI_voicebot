#!/usr/bin/env python3
"""
Statistical significance testing for bhAI STT model benchmarking.

Validates whether the observed nWER differences between models are
statistically significant, using five complementary methods:

  1. Binomial Proportion CI  — quick check, treats words as Bernoulli trials
  2. Paired Bootstrap Test   — gold standard for ASR, resamples utterances
  3. Wilcoxon Signed-Rank    — non-parametric paired test per utterance
  4. Per-Domain Consistency  — checks if winner is consistent across domains
  5. Power Analysis          — is 175 recordings enough?

Usage:
    python benchmarking/scripts/statistical_significance.py
    python benchmarking/scripts/statistical_significance.py --output benchmarking/results/significance.json
    python benchmarking/scripts/statistical_significance.py --bootstraps 50000 --seed 123
"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarking.scripts.compare_models import load_model_transcriptions
from benchmarking.scripts.compute_wer import compute_wer
from benchmarking.scripts.load_ground_truth import load_ground_truth
from benchmarking.scripts.normalize_indic import normalize_hindi


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class UtteranceResult:
    audio_file: str
    domain: str
    wer: float
    errors: int
    ref_words: int


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def collect_per_utterance_wer(
    ground_truth: dict[str, str],
    model_transcriptions: dict[str, dict[str, str]],
) -> dict[str, list[UtteranceResult]]:
    """For each model, compute per-utterance nWER against ground truth."""
    per_model: dict[str, list[UtteranceResult]] = {}

    for model_name, transcriptions in model_transcriptions.items():
        results = []
        for audio_file in sorted(ground_truth.keys()):
            hypothesis = transcriptions.get(audio_file)
            if hypothesis is None:
                continue

            reference = ground_truth[audio_file]
            hyp_norm = normalize_hindi(hypothesis)
            ref_norm = normalize_hindi(reference)
            wer, errors, ref_words = compute_wer(hyp_norm, ref_norm)

            if ref_words == 0:
                continue

            domain = audio_file.split("/")[0]
            results.append(UtteranceResult(audio_file, domain, wer, errors, ref_words))

        per_model[model_name] = results

    return per_model


def identify_models(
    per_model: dict[str, list[UtteranceResult]],
) -> tuple[str, str, list[str]]:
    """Identify best model (lowest aggregate nWER) and closest competitor."""
    agg = {}
    for model, utts in per_model.items():
        total_err = sum(u.errors for u in utts)
        total_words = sum(u.ref_words for u in utts)
        agg[model] = total_err / total_words if total_words else 1.0

    ranked = sorted(agg, key=agg.get)
    best = ranked[0]
    closest = ranked[1]
    others = ranked[2:]
    return best, closest, others


# ---------------------------------------------------------------------------
# Test 1: Binomial Proportion CI
# ---------------------------------------------------------------------------

def binomial_proportion_ci(
    utterances: list[UtteranceResult],
    confidence: float = 0.95,
) -> dict:
    """Treat each word as a Bernoulli trial; compute CI for error rate."""
    total_errors = sum(u.errors for u in utterances)
    total_words = sum(u.ref_words for u in utterances)
    p = total_errors / total_words if total_words else 0.0

    alpha = 1 - confidence
    z = stats.norm.ppf(1 - alpha / 2)
    se = np.sqrt(p * (1 - p) / total_words) if total_words else 0.0

    return {
        "p": p,
        "se": se,
        "ci_lower": p - z * se,
        "ci_upper": p + z * se,
        "total_errors": total_errors,
        "total_words": total_words,
        "z": z,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Test 2: Paired Bootstrap Test
# ---------------------------------------------------------------------------

def paired_bootstrap_test(
    utterances_a: list[UtteranceResult],
    utterances_b: list[UtteranceResult],
    n_bootstrap: int = 10_000,
    confidence: float = 0.95,
    seed: int = 42,
) -> dict:
    """
    Paired bootstrap: resample utterances, compute aggregate nWER difference.

    Returns negative observed_diff when model A is better (lower nWER).
    p-value: fraction of bootstraps where diff >= 0 (A is not better).
    """
    # Align on common audio files
    files_a = {u.audio_file: u for u in utterances_a}
    files_b = {u.audio_file: u for u in utterances_b}
    common = sorted(set(files_a) & set(files_b))

    errors_a = np.array([files_a[f].errors for f in common])
    errors_b = np.array([files_b[f].errors for f in common])
    ref_words = np.array([files_a[f].ref_words for f in common])

    n = len(common)
    observed_wer_a = errors_a.sum() / ref_words.sum()
    observed_wer_b = errors_b.sum() / ref_words.sum()
    observed_diff = observed_wer_a - observed_wer_b

    rng = np.random.default_rng(seed)
    indices = rng.integers(0, n, size=(n_bootstrap, n))

    boot_err_a = errors_a[indices].sum(axis=1)
    boot_err_b = errors_b[indices].sum(axis=1)
    boot_words = ref_words[indices].sum(axis=1)

    boot_wer_a = boot_err_a / boot_words
    boot_wer_b = boot_err_b / boot_words
    diffs = boot_wer_a - boot_wer_b

    alpha = 1 - confidence
    ci_lower = float(np.percentile(diffs, 100 * alpha / 2))
    ci_upper = float(np.percentile(diffs, 100 * (1 - alpha / 2)))
    p_value = float(np.mean(diffs >= 0))

    return {
        "observed_diff": float(observed_diff),
        "mean_bootstrap_diff": float(np.mean(diffs)),
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "p_value": p_value,
        "significant": p_value < alpha,
        "n_common": n,
        "n_bootstrap": n_bootstrap,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Test 3: Wilcoxon Signed-Rank Test
# ---------------------------------------------------------------------------

def wilcoxon_signed_rank_test(
    utterances_a: list[UtteranceResult],
    utterances_b: list[UtteranceResult],
) -> dict:
    """Non-parametric paired test on per-utterance nWER differences."""
    files_a = {u.audio_file: u for u in utterances_a}
    files_b = {u.audio_file: u for u in utterances_b}
    common = sorted(set(files_a) & set(files_b))

    wer_a = np.array([files_a[f].wer for f in common])
    wer_b = np.array([files_b[f].wer for f in common])
    diffs = wer_a - wer_b

    n_ties = int(np.sum(diffs == 0))
    n_nonzero = len(diffs) - n_ties

    if n_nonzero == 0:
        return {
            "statistic": 0.0,
            "p_value": 1.0,
            "n_pairs": len(common),
            "n_nonzero": 0,
            "n_ties": n_ties,
            "median_diff": 0.0,
            "mean_diff": 0.0,
        }

    result = stats.wilcoxon(diffs, alternative="two-sided")

    return {
        "statistic": float(result.statistic),
        "p_value": float(result.pvalue),
        "n_pairs": len(common),
        "n_nonzero": n_nonzero,
        "n_ties": n_ties,
        "median_diff": float(np.median(diffs)),
        "mean_diff": float(np.mean(diffs)),
    }


# ---------------------------------------------------------------------------
# Test 4: Per-Domain Consistency
# ---------------------------------------------------------------------------

def per_domain_analysis(
    per_model: dict[str, list[UtteranceResult]],
    min_domain_size: int = 10,
) -> dict:
    """Check if the best model ranks #1 in every domain with sufficient data."""
    # Collect all domains
    all_domains = set()
    for utts in per_model.values():
        for u in utts:
            all_domains.add(u.domain)

    domains_result = {}
    sufficient_count = 0
    consistent = True
    best_overall = identify_models(per_model)[0]

    for domain in sorted(all_domains):
        domain_models = {}
        for model, utts in per_model.items():
            domain_utts = [u for u in utts if u.domain == domain]
            if not domain_utts:
                continue
            total_err = sum(u.errors for u in domain_utts)
            total_words = sum(u.ref_words for u in domain_utts)
            domain_models[model] = {
                "nwer": total_err / total_words if total_words else 1.0,
                "files": len(domain_utts),
                "errors": total_err,
                "words": total_words,
            }

        n_files = max((v["files"] for v in domain_models.values()), default=0)
        sufficient = n_files >= min_domain_size
        if sufficient:
            sufficient_count += 1

        ranked = sorted(domain_models.items(), key=lambda x: x[1]["nwer"])
        rankings = [
            {"model": m, "nwer": round(v["nwer"], 4), "rank": i + 1}
            for i, (m, v) in enumerate(ranked)
        ]

        top_model = ranked[0][0] if ranked else None
        gap = ranked[1][1]["nwer"] - ranked[0][1]["nwer"] if len(ranked) > 1 else 0.0

        if sufficient and top_model != best_overall:
            consistent = False

        domains_result[domain] = {
            "n_files": n_files,
            "sufficient_data": sufficient,
            "rankings": rankings,
            "top_model": top_model,
            "gap_to_second": round(gap, 4),
        }
        if not sufficient:
            domains_result[domain]["warning"] = f"Only {n_files} files - results unreliable"

    return {
        "domains": domains_result,
        "consistent_winner": consistent,
        "best_model": best_overall,
        "domains_with_sufficient_data": sufficient_count,
    }


# ---------------------------------------------------------------------------
# Test 5: Power Analysis
# ---------------------------------------------------------------------------

def power_analysis(
    utterances_a: list[UtteranceResult],
    utterances_b: list[UtteranceResult],
    alpha: float = 0.05,
    n_bootstrap_power: int = 1_000,
    n_inner_bootstrap: int = 500,
    seed: int = 42,
) -> dict:
    """
    Two-pronged power analysis: binomial z-test + bootstrap-based.

    Tests current sample and projects minimum N needed.
    """
    files_a = {u.audio_file: u for u in utterances_a}
    files_b = {u.audio_file: u for u in utterances_b}
    common = sorted(set(files_a) & set(files_b))

    errors_a = np.array([files_a[f].errors for f in common])
    errors_b = np.array([files_b[f].errors for f in common])
    ref_words = np.array([files_a[f].ref_words for f in common])

    n_utts = len(common)
    total_words = int(ref_words.sum())
    avg_words_per_file = total_words / n_utts if n_utts else 1

    p_a = errors_a.sum() / ref_words.sum()
    p_b = errors_b.sum() / ref_words.sum()
    effect_size = float(p_b - p_a)

    per_utt_diffs = np.array([
        files_a[f].wer - files_b[f].wer for f in common
    ])
    observed_variance = float(np.var(per_utt_diffs, ddof=1))

    # --- Binomial z-test approach ---
    pooled_p = (errors_a.sum() + errors_b.sum()) / (2 * ref_words.sum())
    z_alpha = stats.norm.ppf(1 - alpha / 2)

    def binomial_power(n_words: int) -> float:
        se = np.sqrt(2 * pooled_p * (1 - pooled_p) / n_words) if n_words > 0 else float("inf")
        if se == 0:
            return 1.0
        z_beta = effect_size / se - z_alpha
        return float(stats.norm.cdf(z_beta))

    current_power_binom = binomial_power(total_words)

    targets = [0.80, 0.90, 0.95]
    min_words = {}
    min_files = {}
    for target in targets:
        n = 10
        while n < 10_000_000:
            if binomial_power(n) >= target:
                break
            n = int(n * 1.5) + 1
        # Refine with binary search
        lo, hi = max(10, n // 2), n
        while lo < hi:
            mid = (lo + hi) // 2
            if binomial_power(mid) >= target:
                hi = mid
            else:
                lo = mid + 1
        min_words[target] = lo
        min_files[target] = max(1, int(np.ceil(lo / avg_words_per_file)))

    binom_result = {
        "current_N_words": total_words,
        "current_power": round(current_power_binom, 4),
        "avg_words_per_file": round(avg_words_per_file, 1),
    }
    for t in targets:
        key = f"min_words_for_{int(t*100)}pct"
        binom_result[key] = min_words[t]
        binom_result[f"min_files_for_{int(t*100)}pct"] = min_files[t]

    # --- Bootstrap-based power ---
    rng = np.random.default_rng(seed)
    sample_sizes = [10, 25, 50, 75, 100, 125, 150, 175, 250, 500]
    # Only test sizes up to 2x our actual data (can't bootstrap beyond our pool)
    sample_sizes = [s for s in sample_sizes if s <= n_utts * 2]
    if n_utts not in sample_sizes:
        sample_sizes.append(n_utts)
        sample_sizes.sort()

    power_curve = []

    for n_files_test in sample_sizes:
        sig_count = 0
        for _ in range(n_bootstrap_power):
            # Subsample n_files_test utterances from the pool (with replacement)
            sub_idx = rng.integers(0, n_utts, size=n_files_test)
            sub_err_a = errors_a[sub_idx]
            sub_err_b = errors_b[sub_idx]
            sub_words = ref_words[sub_idx]

            # Inner bootstrap test on this subsample
            inner_idx = rng.integers(0, n_files_test, size=(n_inner_bootstrap, n_files_test))
            inner_err_a = sub_err_a[inner_idx].sum(axis=1)
            inner_err_b = sub_err_b[inner_idx].sum(axis=1)
            inner_words = sub_words[inner_idx].sum(axis=1)

            inner_diffs = inner_err_a / inner_words - inner_err_b / inner_words
            p_val = float(np.mean(inner_diffs >= 0))

            if p_val < alpha:
                sig_count += 1

        power = sig_count / n_bootstrap_power
        power_curve.append({"n_files": n_files_test, "power": round(power, 3)})

    bootstrap_min_files = {}
    for target in targets:
        for entry in power_curve:
            if entry["power"] >= target:
                bootstrap_min_files[target] = entry["n_files"]
                break
        else:
            bootstrap_min_files[target] = None  # not reached

    bootstrap_result = {
        "power_curve": power_curve,
    }
    for t in targets:
        bootstrap_result[f"min_files_for_{int(t*100)}pct"] = bootstrap_min_files[t]

    return {
        "observed_effect_size": round(effect_size, 4),
        "observed_variance": round(observed_variance, 4),
        "binomial_approach": binom_result,
        "bootstrap_approach": bootstrap_result,
    }


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def _sig_stars(p: float) -> str:
    if p < 0.001:
        return "***"
    elif p < 0.01:
        return "**"
    elif p < 0.05:
        return "*"
    return ""


def _fmt_p(p: float) -> str:
    if p < 0.0001:
        return "<0.0001"
    elif p < 0.001:
        return f"{p:.4f}"
    else:
        return f"{p:.4f}"


def print_report(
    per_model: dict[str, list[UtteranceResult]],
    best: str,
    closest: str,
    others: list[str],
    binom_results: dict[str, dict],
    bootstrap_results: dict[str, dict],
    wilcoxon_result: dict,
    domain_result: dict,
    power_result: dict,
) -> None:
    """Print the full formatted report to stdout."""

    best_nwer = binom_results[best]["p"]
    closest_nwer = binom_results[closest]["p"]
    gap = closest_nwer - best_nwer
    total_words = binom_results[best]["total_words"]
    n_files = len(per_model[best])

    W = 80

    print("=" * W)
    print("STATISTICAL SIGNIFICANCE REPORT".center(W))
    print("bhAI STT Model Benchmarking".center(W))
    print("=" * W)
    print()
    print(f"  Dataset:             {n_files} utterances, {total_words} total reference words")
    print(f"  Primary metric:      nWER (normalized Word Error Rate, lower = better)")
    print(f"  Best model:          {best} (nWER = {best_nwer:.2%})")
    print(f"  Closest competitor:  {closest} (nWER = {closest_nwer:.2%})")
    print(f"  Gap:                 {gap:.2%} ({gap*100:.2f} percentage points)")

    # --- Test 1: Binomial CI ---
    print()
    print("-" * W)
    print("  1. BINOMIAL PROPORTION CONFIDENCE INTERVALS")
    print("-" * W)
    print()
    print("  Each word treated as an independent Bernoulli trial (correct / incorrect).")
    print(f"  N = total reference words across all {n_files} utterances.")
    print()
    print(f"  {'Model':<50} {'nWER':>7}    {'95% CI':>20}    {'N (words)':>10}")

    for model in [best, closest]:
        b = binom_results[model]
        ci_str = f"[{b['ci_lower']:.2%}, {b['ci_upper']:.2%}]"
        print(f"  {model:<50} {b['p']:>6.2%}    {ci_str:>20}    {b['total_words']:>10}")

    b_best = binom_results[best]
    b_close = binom_results[closest]
    overlap = b_best["ci_upper"] >= b_close["ci_lower"]

    print()
    if not overlap:
        print("  CIs DO NOT OVERLAP --> statistically significant difference (binomial model).")
    else:
        print("  CIs OVERLAP --> difference may not be significant under binomial model.")

    print()
    print("  Caveat: The binomial model assumes word-level independence. In practice,")
    print("  errors cluster within utterances, making these CIs anti-conservative")
    print("  (too narrow). See the bootstrap test below for a more robust analysis.")

    # --- Test 2: Paired Bootstrap ---
    print()
    print("-" * W)
    print("  2. PAIRED BOOTSTRAP TEST (B = {:,})".format(
        bootstrap_results[closest]["n_bootstrap"]
    ))
    print("-" * W)
    print()
    print("  Resampling unit: utterances (accounts for within-utterance correlation).")
    print("  H0: {} is not better than the competitor.".format(best))
    print("  Test: one-sided (is {} strictly better?).".format(best))
    print()
    print(f"  {'Comparison':<45} {'Observed':>9}  {'95% Bootstrap CI':>22}  {'p-value':>12}")

    all_competitors = [closest] + others
    for comp in all_competitors:
        br = bootstrap_results[comp]
        diff_pp = br["observed_diff"] * 100
        ci_str = f"[{br['ci_lower']*100:+.2f}pp, {br['ci_upper']*100:+.2f}pp]"
        p_str = _fmt_p(br["p_value"])
        stars = _sig_stars(br["p_value"])
        print(f"  {best} vs {comp:<30} {diff_pp:>+7.2f}pp  {ci_str:>22}  {p_str:>8} {stars}")

    print()
    print(f"  Significance: *** p < 0.001, ** p < 0.01, * p < 0.05")
    br_close = bootstrap_results[closest]
    if br_close["p_value"] < 0.05:
        print(f"\n  The 95% bootstrap CI for {best} vs {closest} excludes zero entirely.")
    else:
        print(f"\n  The 95% bootstrap CI for {best} vs {closest} includes zero.")

    # --- Test 3: Wilcoxon ---
    print()
    print("-" * W)
    print(f"  3. WILCOXON SIGNED-RANK TEST ({best} vs {closest})")
    print("-" * W)
    print()
    print("  Per-utterance nWER paired comparison (non-parametric).")
    print("  H0: the distribution of per-utterance WER differences is symmetric about 0.")
    print()
    w = wilcoxon_result
    p_str = _fmt_p(w["p_value"])
    stars = _sig_stars(w["p_value"])
    print(f"  Statistic (W):         {w['statistic']:.1f}")
    print(f"  p-value (two-sided):   {p_str} {stars}")
    print(f"  Non-zero pairs:        {w['n_nonzero']} / {w['n_pairs']}")
    print(f"  Ties (identical WER):  {w['n_ties']}")
    print(f"  Median per-utt diff:   {w['median_diff']*100:+.2f} pp")
    print(f"  Mean per-utt diff:     {w['mean_diff']*100:+.2f} pp")
    print()
    if w["p_value"] < 0.05:
        print(f"  Result: REJECT H0 (p {p_str}). {best} has significantly lower")
        print(f"  per-utterance WER than {closest}.")
    else:
        print(f"  Result: FAIL TO REJECT H0. Difference is not significant at p < 0.05.")

    # --- Test 4: Per-Domain ---
    print()
    print("-" * W)
    print("  4. PER-DOMAIN CONSISTENCY")
    print("-" * W)
    print()
    print(f"  {'Domain':<15} {'Files':>5}  {best+' nWER':>14}  {'#2 model':<25} {'#2 nWER':>8}  {'Gap':>7}  {'Rank':>6}")

    dr = domain_result
    for domain in sorted(dr["domains"]):
        d = dr["domains"][domain]
        rankings = d["rankings"]
        if not rankings:
            continue
        top = rankings[0]
        second = rankings[1] if len(rankings) > 1 else None

        best_nwer_d = None
        for r in rankings:
            if r["model"] == best:
                best_nwer_d = r["nwer"]
                best_rank = r["rank"]
                break

        if best_nwer_d is None:
            continue

        flag = "  [!]" if not d["sufficient_data"] else ""
        second_model = second["model"] if second else "—"
        second_nwer = second["nwer"] if second else 0
        gap_d = d["gap_to_second"] if top["model"] == best else -(best_nwer_d - top["nwer"])

        # Truncate long model names
        second_short = second_model[:25] if second_model else "—"
        print(
            f"  {domain:<15} {d['n_files']:>5}  "
            f"{best_nwer_d:>13.2%}  "
            f"{second_short:<25} {second_nwer:>7.2%}  "
            f"{gap_d*100:>+6.2f}pp  "
            f"#{best_rank}{flag}"
        )

    print()
    if not dr["consistent_winner"]:
        print(f"  [!] = fewer than 10 files (unreliable).")
        print(f"  {best} is NOT the winner in all domains with sufficient data.")
    else:
        n_suff = dr["domains_with_sufficient_data"]
        print(f"  [!] = fewer than 10 files (unreliable, excluded from consistency check).")
        print(f"  {best} ranks #1 in ALL {n_suff} domains with sufficient data.")

    # --- Test 5: Power Analysis ---
    print()
    print("-" * W)
    print("  5. SAMPLE SIZE ADEQUACY / POWER ANALYSIS")
    print("-" * W)
    print()
    pr = power_result
    print(f"  Effect size ({best} vs {closest}): {pr['observed_effect_size']*100:.2f} percentage points")
    print(f"  Per-utterance WER difference std dev: {np.sqrt(pr['observed_variance'])*100:.2f} pp")
    print()

    # Binomial approach
    ba = pr["binomial_approach"]
    print(f"  a) Binomial z-test approach (N = total reference words):")
    print(f"     Current N = {ba['current_N_words']} words --> power = {ba['current_power']:.1%}")
    for t in [80, 90, 95]:
        nw = ba.get(f"min_words_for_{t}pct", "?")
        nf = ba.get(f"min_files_for_{t}pct", "?")
        print(f"     For {t}% power: need ~{nw} words (~{nf} files)")
    print()

    # Bootstrap approach
    bba = pr["bootstrap_approach"]
    print(f"  b) Bootstrap approach (N = number of utterances/files):")
    print(f"     {'N (files)':>10}    {'Estimated Power':>16}")
    for entry in bba["power_curve"]:
        marker = "  <-- current sample size" if entry["n_files"] == n_files else ""
        print(f"     {entry['n_files']:>10}    {entry['power']:>15.1%}{marker}")

    print()
    for t in [80, 90, 95]:
        nf = bba.get(f"min_files_for_{t}pct")
        if nf is not None:
            print(f"     For {t}% power: need ~{nf} files")
        else:
            print(f"     For {t}% power: need >{bba['power_curve'][-1]['n_files']} files")

    current_boot_power = None
    for entry in bba["power_curve"]:
        if entry["n_files"] == n_files:
            current_boot_power = entry["power"]
            break

    # --- Summary Verdict ---
    print()
    print("=" * W)
    print("SUMMARY VERDICT".center(W))
    print("=" * W)
    print()

    binom_sig = not overlap
    boot_sig = br_close["p_value"] < 0.05
    wilcox_sig = w["p_value"] < 0.05
    domain_ok = dr["consistent_winner"]
    n_suff = dr["domains_with_sufficient_data"]

    boot_p_str = _fmt_p(br_close["p_value"])
    boot_stars = _sig_stars(br_close["p_value"])
    wilcox_p_str = _fmt_p(w["p_value"])
    wilcox_stars = _sig_stars(w["p_value"])

    power_str = f"{current_boot_power:.0%}" if current_boot_power else f"{ba['current_power']:.0%}"

    # Column 1: Test name + result
    # Column 2: Plain English explanation
    print(f"  Test                 Result              What it means")
    print(f"  {'─' * 74}")
    print()

    # 1. Binomial
    r1 = "Non-overlapping" if binom_sig else "OVERLAPPING"
    print(f"  1. Binomial CIs      {r1:<20}")
    if binom_sig:
        print(f"     If we repeated this experiment many times, 95% of the time {best}'s")
        print(f"     true error rate would stay below {closest}'s. The gap is not a fluke.")
    else:
        print(f"     The confidence intervals overlap — we can't rule out that the true error")
        print(f"     rates are similar. More data may be needed.")
    print()

    # 2. Bootstrap
    r2 = f"p {boot_p_str} {boot_stars}"
    print(f"  2. Paired bootstrap  {r2:<20}")
    if boot_sig:
        print(f"     We reshuffled which recordings were included 10,000 times. {best}")
        print(f"     beat {closest} virtually every time — there's no realistic")
        print(f"     resample of our data where {closest} catches up.")
    else:
        print(f"     When reshuffling which recordings are included, {closest} sometimes")
        print(f"     catches up to {best}. The difference is not robust to resampling.")
    print()

    # 3. Wilcoxon
    r3 = f"p {wilcox_p_str} {wilcox_stars}"
    print(f"  3. Wilcoxon          {r3:<20}")
    if wilcox_sig:
        print(f"     Looking at individual recordings (not just totals), {best}")
        print(f"     consistently makes fewer errors per recording than {closest}.")
        print(f"     It's not that {best} is great on a few easy ones and bad on the")
        print(f"     rest — it wins broadly across recordings.")
    else:
        print(f"     On a per-recording basis, the differences are not consistent enough")
        print(f"     to be statistically significant.")
    print()

    # 4. Domain
    r4 = f"#1 in {n_suff}/{n_suff} domains" if domain_ok else f"NOT #1 in all domains"
    print(f"  4. Domain            {r4:<20}")
    if domain_ok:
        print(f"     {best} doesn't just win overall — it wins in every domain")
        print(f"     (helpdesk, HR-admin, production) separately. The advantage is real")
        print(f"     across different types of conversations.")
    else:
        print(f"     {best} does not win in every domain. The overall result may be")
        print(f"     driven by strong performance in some domains but not others.")
    print()

    # 5. Power
    r5 = f"{power_str} at N={n_files}"
    print(f"  5. Power analysis    {r5:<20}")
    boot_80 = bba.get("min_files_for_80pct")
    if current_boot_power and current_boot_power >= 0.80:
        print(f"     {n_files} recordings is more than enough to detect the")
        print(f"     {pr['observed_effect_size']*100:.1f}pp gap we observed.")
        if boot_80:
            print(f"     We'd need only ~{boot_80} files for 80% power.")
        print(f"     Our sample size is not a concern.")
    else:
        print(f"     At N={n_files}, statistical power is below 80%. Consider")
        print(f"     collecting more recordings to strengthen the conclusion.")

    # Final conclusion
    all_sig = binom_sig and boot_sig and wilcox_sig and domain_ok
    print()
    print(f"  {'─' * 74}")
    print()
    print(f"  WHAT THIS MEANS FOR bhAI:")
    if all_sig:
        print(f"  The data strongly supports choosing {best}. The {gap*100:.1f}pp nWER")
        print(f"  advantage over {closest} is statistically significant by every test")
        print(f"  we ran. This is not a marginal call — it's a clear winner for Hindi")
        print(f"  voice transcription quality.")
    elif boot_sig:
        print(f"  The data supports choosing {best}, with the paired bootstrap test")
        print(f"  (the most robust method) confirming significance. Some secondary")
        print(f"  tests show weaker evidence — consider collecting more data.")
    else:
        print(f"  The evidence is not strong enough to conclusively declare {best}")
        print(f"  the winner. Consider collecting more recordings before committing.")

    print()
    print(f"  CAVEATS:")
    print(f"  - These {n_files} recordings come from Tiny Miracles artisans. If bhAI")
    print(f"    expands to very different speakers/dialects, re-validation is prudent.")

    # Find production gap
    prod_domain = dr["domains"].get("production", {})
    if prod_domain.get("sufficient_data"):
        prod_gap = prod_domain.get("gap_to_second", 0)
        if prod_gap < 0.03:
            print(f"  - Production domain has the smallest gap ({prod_gap*100:.2f}pp).")
            print(f"    Collecting more production recordings would strengthen that claim.")

    small_domains = [d for d, v in dr["domains"].items() if not v.get("sufficient_data")]
    if small_domains:
        print(f"  - {', '.join(d.capitalize() for d in small_domains)}: too few files for conclusions.")

    print()
    print("=" * W)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Statistical significance testing for STT model benchmarking"
    )
    parser.add_argument(
        "--output",
        help="Save structured results to JSON",
    )
    parser.add_argument(
        "--xlsx",
        help="Path to ground-truth xlsx",
    )
    parser.add_argument(
        "--bootstraps", type=int, default=10_000,
        help="Number of bootstrap iterations (default: 10000)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Load data
    xlsx_path = Path(args.xlsx) if args.xlsx else None
    ground_truth = load_ground_truth(xlsx_path)
    model_transcriptions = load_model_transcriptions()

    print(f"Loading data: {len(ground_truth)} ground truth entries, "
          f"{len(model_transcriptions)} models")
    print("Computing per-utterance nWER for all models...")

    per_model = collect_per_utterance_wer(ground_truth, model_transcriptions)
    best, closest, others = identify_models(per_model)

    print(f"Best model: {best}, closest competitor: {closest}")
    print(f"Running statistical tests (bootstrap B={args.bootstraps})...\n")

    # Test 1: Binomial CI for each model
    binom_results = {}
    for model in [best, closest] + others:
        binom_results[model] = binomial_proportion_ci(per_model[model])

    # Test 2: Paired bootstrap for best vs each competitor
    bootstrap_results = {}
    for comp in [closest] + others:
        bootstrap_results[comp] = paired_bootstrap_test(
            per_model[best], per_model[comp],
            n_bootstrap=args.bootstraps,
            seed=args.seed,
        )

    # Test 3: Wilcoxon for best vs closest
    wilcoxon_result = wilcoxon_signed_rank_test(per_model[best], per_model[closest])

    # Test 4: Per-domain consistency
    domain_result = per_domain_analysis(per_model)

    # Test 5: Power analysis
    print("Running power analysis (this may take a moment)...")
    power_result = power_analysis(
        per_model[best], per_model[closest],
        seed=args.seed,
    )

    # Print report
    print()
    print_report(
        per_model, best, closest, others,
        binom_results, bootstrap_results,
        wilcoxon_result, domain_result, power_result,
    )

    # Save JSON
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        export = {
            "dataset": {
                "n_files": len(per_model[best]),
                "total_words": binom_results[best]["total_words"],
                "best_model": best,
                "closest_competitor": closest,
            },
            "binomial_ci": {
                model: {k: v for k, v in res.items()}
                for model, res in binom_results.items()
            },
            "bootstrap_tests": {
                comp: {k: v for k, v in res.items()}
                for comp, res in bootstrap_results.items()
            },
            "wilcoxon": wilcoxon_result,
            "domain_consistency": domain_result,
            "power_analysis": power_result,
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(export, f, indent=2, ensure_ascii=False)
        print(f"\nStructured results saved to: {output_path}")


if __name__ == "__main__":
    main()
