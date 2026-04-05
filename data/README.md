# Data Directory

This directory contains audio data and transcription datasets for bhAI.

## Structure

```
data/
├── sample_audio/              # Example audio files for dev/testing
│
├── sharepoint_sync/           # Audio files (unzipped from sharepoint_audio.zip)
│   ├── helpdesk/              # 114 Q files
│   ├── hr_admin/              # 30 Q files
│   ├── production/            # 28 Q files
│   ├── grievance/             # 2 Q files
│   └── nextgen/               # 2 Q files
│
└── transcription_dataset/     # Per-model STT transcriptions
    ├── helpdesk/
    │   ├── transcriptions.jsonl                  # Legacy (mixed models)
    │   ├── transcriptions_sarvam_saaras.jsonl
    │   ├── transcriptions_sarvam_saarika.jsonl
    │   ├── transcriptions_indic_conformer.jsonl
    │   ├── transcriptions_vaani_whisper.jsonl
    │   ├── transcriptions_whisper_large_v3.jsonl
    │   ├── transcriptions_meta_mms.jsonl
    │   └── transcriptions_indic_wav2vec.jsonl
    ├── hr_admin/               # Same per-model JSONL structure
    ├── production/             # Same per-model JSONL structure
    ├── grievance/              # Same per-model JSONL structure
    └── nextgen/                # Same per-model JSONL structure
```

## SharePoint Sync

Audio files are automatically synced from the shared SharePoint folder.

### Setup (one-time)

```bash
# Run the setup script
./scripts/setup_sharepoint_sync.sh
```

### Manual Sync

```bash
# Trigger a sync
./scripts/sync_sharepoint.sh
```

### Auto Sync

The sync runs automatically every hour via launchd (macOS) or cron (Linux).

## Transcription Dataset

### Format

Each transcription file uses JSONL format (one JSON object per line):

```jsonl
{"audio_file": "hr_admin/HR_Ad_Q_1.ogg", "stt_model": "saaras:v3", "stt_draft": "मेरा पैसा क्यों काटे", "latency_seconds": 2.27, "human_reviewed": null, "final": null, "status": "pending_review", "timestamp": "2026-02-25T05:09:27.472942"}
```

### Fields

| Field | Description |
|-------|-------------|
| `audio_file` | Path to audio file (relative to sharepoint_sync/) |
| `stt_model` | Model used for initial transcription |
| `stt_draft` | Initial STT output |
| `human_reviewed` | Corrected transcription by reviewer |
| `final` | Final approved transcription |
| `latency_seconds` | STT processing time |
| `status` | `pending_review`, `reviewed`, `approved` |
| `timestamp` | When the transcription was generated |

### Workflow

1. **STT First Pass**: Run `benchmarking/scripts/generate_initial_transcriptions.py`
2. **Human Review**: Edit `transcriptions.jsonl`, fix errors in `human_reviewed`
3. **Approval**: Set `status` to `approved`, copy `human_reviewed` to `final`

## Notes

- Audio files are NOT committed to git (too large) — packaged as `sharepoint_audio.zip` at project root
- JSONL transcription files ARE committed for tracking and reproducibility
- Ground truth lives in `source_of_truth_transcriptions.xlsx` (176 entries, project root)
