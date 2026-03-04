# STT Benchmarking

This directory contains tools for benchmarking Speech-to-Text models on bhAI audio data.

For detailed methodology, normalization pipeline, and results, see [BENCHMARKING.md](BENCHMARKING.md).

## Overview

The benchmarking workflow:
1. **Generate transcriptions** using 7 STT models (2 API + 5 GPU)
2. **Human review** to create ground truth (176 recordings across 5 domains)
3. **Compare models** (WER, CER, SemDist with Indic text normalization)
4. **Statistical validation** to confirm the findings

## Scripts

| Script | Purpose |
|--------|---------|
| `generate_initial_transcriptions.py` | Run STT models on audio files |
| `transcribe_questions.py` | Sarvam-specific batch transcription |
| `compare_models.py` | Main comparison (6 metrics: raw WER/CER, nWER/nCER, SemDist) |
| `compute_wer.py` | WER/CER/SemDist computation |
| `normalize_indic.py` | Indic text normalization (time, currency, numbers, punct, Unicode) |
| `error_analysis.py` | Waterfall error breakdown per model |
| `statistical_significance.py` | Statistical validation (bootstrap, Wilcoxon, power analysis) |
| `load_ground_truth.py` | Read ground truth from xlsx |
| `download_audio_from_sharepoint.py` | SharePoint audio sync |
| `extract_voice2voice_questions.py` | Extract Q files from Voice2Voice.zip |

## Quick Start

```bash
# Compare all models (all domains)
python3 benchmarking/scripts/compare_models.py

# Per-domain comparison with CSV output
python3 benchmarking/scripts/compare_models.py --domain helpdesk --output benchmarking/results/comparison_helpdesk.csv

# Error analysis waterfall
python3 benchmarking/scripts/error_analysis.py --domain helpdesk

# Statistical significance report
python3 benchmarking/scripts/statistical_significance.py
```

## Models

| Model | Type | nWER (all domains) |
|-------|------|------|
| saaras:v3 | API (Sarvam) | **6.76%** |
| saarika:v2.5 | API (Sarvam) | 12.83% |
| indic-conformer-600m | HuggingFace (GPU) | 25.80% |
| vaani-whisper | HuggingFace (GPU) | 39.52% |
| mms-1b-all | HuggingFace (GPU) | 51.60% |
| indicwav2vec-hindi | HuggingFace (GPU) | 55.22% |
| whisper-large-v3 | HuggingFace (GPU) | 57.47% |

## Metrics

- **nWER (Normalized Word Error Rate)**: Primary ranking metric — WER after Indic text normalization
- **nCER (Normalized Character Error Rate)**: Character-level normalized metric
- **SemDist (Semantic Distance)**: 1 - cosine similarity using Vyakyarth-1 Indic embeddings
- **Raw WER/CER**: Without normalization (for reference)

## Results

Results are saved in `results/`:

| File | Contents |
|------|----------|
| `comparison_all.csv` | All-domains model comparison |
| `comparison_{domain}.csv` | Per-domain results |
| `significance.json` | Statistical significance test results |

## GPU Benchmarking

GPU models run on an EC2 g4dn.xlarge instance. See [EC2_SETUP.md](EC2_SETUP.md) for setup instructions.
