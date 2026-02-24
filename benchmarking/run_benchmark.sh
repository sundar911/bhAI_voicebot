#!/usr/bin/env bash
# =============================================================================
# bhAI STT Benchmarking — run all models on all domains
#
# Usage:
#   bash benchmarking/run_benchmark.sh
#   bash benchmarking/run_benchmark.sh --models "meta_mms vaani_whisper"
#   bash benchmarking/run_benchmark.sh --domains "hr_admin"
#   bash benchmarking/run_benchmark.sh --device cpu
# =============================================================================
set -euo pipefail

# ── Defaults ─────────────────────────────────────────────────────────────────
MODELS="vaani_whisper indic_conformer whisper_large_v3 meta_mms indic_wav2vec"
DOMAINS="hr_admin helpdesk production"
DEVICE="cuda"

# ── Parse CLI args ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --models)  MODELS="$2";  shift 2 ;;
        --domains) DOMAINS="$2"; shift 2 ;;
        --device)  DEVICE="$2";  shift 2 ;;
        -h|--help)
            echo "Usage: bash benchmarking/run_benchmark.sh [--models \"m1 m2\"] [--domains \"d1 d2\"] [--device cuda]"
            echo ""
            echo "Options:"
            echo "  --models   Space-separated model names (default: all 5 GPU models)"
            echo "  --domains  Space-separated domain names (default: hr_admin helpdesk production)"
            echo "  --device   cuda or cpu (default: cuda)"
            exit 0 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# ── Resolve project root (script lives in benchmarking/) ─────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# ── Activate venv if present ──────────────────────────────────────────────────
if [[ -f "$ROOT/.venv/bin/activate" ]]; then
    source "$ROOT/.venv/bin/activate"
    log "Activated venv: $ROOT/.venv"
fi

AUDIO_DIR="$ROOT/data/sharepoint_sync"
RESULTS_DIR="$ROOT/benchmarking/results"
XLSX="$ROOT/source_of_truth_transcriptions.xlsx"

# ── 1. HuggingFace login ────────────────────────────────────────────────────
if [[ -n "${HF_TOKEN:-}" ]]; then
    log "Logging into HuggingFace..."
    huggingface-cli login --token "$HF_TOKEN" 2>/dev/null || true
else
    log "WARNING: HF_TOKEN not set. Model downloads may fail for gated models."
    log "  Set it with: export HF_TOKEN=\"hf_your_token_here\""
fi

# ── 2. Verify CUDA (if requested) ───────────────────────────────────────────
if [[ "$DEVICE" == "cuda" ]]; then
    if python3 -c "import torch; assert torch.cuda.is_available()" 2>/dev/null; then
        GPU_NAME=$(python3 -c "import torch; print(torch.cuda.get_device_name(0))")
        VRAM=$(python3 -c "import torch; print(f'{torch.cuda.get_device_properties(0).total_mem/1e9:.1f} GB')")
        log "GPU: $GPU_NAME ($VRAM)"
    else
        log "ERROR: --device cuda but no CUDA GPU detected."
        log "  Either install CUDA drivers or use: --device cpu"
        exit 1
    fi
fi

# ── 3. Verify audio files ───────────────────────────────────────────────────
if [[ ! -d "$AUDIO_DIR" ]]; then
    log "ERROR: Audio directory not found: $AUDIO_DIR"
    log "  Unzip your audio: unzip sharepoint_audio.zip -d data/sharepoint_sync/"
    exit 1
fi

for domain in $DOMAINS; do
    domain_dir="$AUDIO_DIR/$domain"
    if [[ ! -d "$domain_dir" ]]; then
        log "WARNING: No audio directory for domain '$domain': $domain_dir"
    else
        count=$(find "$domain_dir" -type f \( -name "*.ogg" -o -name "*.wav" -o -name "*.mp3" \) | wc -l | tr -d ' ')
        log "Audio files for $domain: $count"
    fi
done

# ── 4. Verify ground truth xlsx ──────────────────────────────────────────────
if [[ ! -f "$XLSX" ]]; then
    log "ERROR: Ground truth not found: $XLSX"
    log "  Copy source_of_truth_transcriptions.xlsx to the project root."
    exit 1
fi
log "Ground truth xlsx: $XLSX"

# ── 5. Run transcriptions ───────────────────────────────────────────────────
mkdir -p "$RESULTS_DIR"

log ""
log "=========================================="
log "  Starting benchmarking"
log "  Models:  $MODELS"
log "  Domains: $DOMAINS"
log "  Device:  $DEVICE"
log "=========================================="

for domain in $DOMAINS; do
    input_dir="$AUDIO_DIR/$domain"
    if [[ ! -d "$input_dir" ]]; then
        log "Skipping $domain — no audio directory"
        continue
    fi

    for model in $MODELS; do
        log ""
        log ">>> $model on $domain"
        python3 benchmarking/scripts/generate_initial_transcriptions.py \
            --model "$model" \
            --input "$input_dir" \
            --domain "$domain" \
            --device "$DEVICE" \
            --append
    done
done

# ── 6. Compare models ───────────────────────────────────────────────────────
log ""
log "=========================================="
log "  Comparing models"
log "=========================================="

for domain in $DOMAINS; do
    log ""
    log ">>> Comparison for $domain"
    python3 benchmarking/scripts/compare_models.py \
        --domain "$domain" \
        --output "$RESULTS_DIR/comparison_${domain}.csv"
done

# ── 7. Summary ───────────────────────────────────────────────────────────────
log ""
log "=========================================="
log "  DONE"
log "=========================================="
log "Results saved to: $RESULTS_DIR/"
ls -la "$RESULTS_DIR/"*.csv 2>/dev/null || log "  (no CSV files generated)"
