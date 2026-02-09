# STT Benchmarking

This directory contains tools for benchmarking Speech-to-Text models on bhAI audio data.

## Overview

The benchmarking workflow:
1. **Generate transcriptions** using STT model(s)
2. **Human review** to create ground truth
3. **Compute metrics** (WER, CER)
4. **Compare models** to select the best one

## Review App

For human review of transcriptions, we have a web-based tool:

```bash
uv run streamlit run benchmarking/review_app.py
```

See [../docs/SETUP_FOR_TINY.md](../docs/SETUP_FOR_TINY.md) for complete setup instructions.
See [../docs/review_instructions.md](../docs/review_instructions.md) for detailed usage.

## Scripts

### `scripts/generate_initial_transcriptions.py`

Generate first-pass STT transcriptions for audio files.

```bash
# Process HR-Admin audio files
uv run python benchmarking/scripts/generate_initial_transcriptions.py \
    --input data/sharepoint_sync/hr_admin/ \
    --domain hr_admin

# Append new files to existing dataset
uv run python benchmarking/scripts/generate_initial_transcriptions.py \
    --input data/sharepoint_sync/hr_admin/ \
    --domain hr_admin \
    --append
```

### `scripts/compute_wer.py`

Compute Word Error Rate (WER) and Character Error Rate (CER).

```bash
# Compute metrics using human_reviewed as reference
uv run python benchmarking/scripts/compute_wer.py \
    --input data/transcription_dataset/hr_admin/transcriptions.jsonl

# Save detailed results
uv run python benchmarking/scripts/compute_wer.py \
    --input data/transcription_dataset/hr_admin/transcriptions.jsonl \
    --output benchmarking/results/hr_admin_wer.json
```

## Models to Benchmark

| Model | Source | Notes |
|-------|--------|-------|
| saarika:v2.5 | Sarvam AI | Current production model |
| whisper-large-v3-vaani-hindi | ARTPARK-IISc | Trained on Vaani dataset |
| IndicWhisper | AI4Bharat | Best on Vistaar benchmarks |
| indic-conformer-600m | AI4Bharat | Modern transformer architecture |

## Metrics

- **WER (Word Error Rate)**: Primary metric for overall accuracy
- **CER (Character Error Rate)**: Useful for Hindi where word boundaries vary
- **Latency**: Processing time per audio file

## Cloud Notebooks

For running models requiring GPU:

1. Open `notebooks/analysis.ipynb` in Google Colab
2. Enable GPU runtime
3. Install dependencies
4. Run benchmarks

## Results

Results are saved in `results/` directory (gitignored).

Format:
```json
{
  "summary": {
    "files_evaluated": 50,
    "overall_wer": 0.15,
    "overall_cer": 0.08
  },
  "per_file": [...]
}
```
