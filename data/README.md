# Data Directory

This directory contains audio data and transcription datasets for bhAI.

## Structure

```
data/
├── sharepoint_sync/           # Auto-synced from SharePoint
│   ├── helpdesk/              # Helpdesk domain audio
│   ├── hr_admin/              # HR-Admin domain audio
│   └── production/            # Production domain audio
│
└── transcription_dataset/     # Ground truth transcriptions
    ├── manifest.csv           # Master tracking file
    ├── hr_admin/
    │   └── transcriptions.jsonl
    ├── helpdesk/
    │   └── transcriptions.jsonl
    └── production/
        └── transcriptions.jsonl
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
{"audio_file": "hr_admin/001.ogg", "stt_model": "saarika:v2.5", "stt_draft": "मेरा पैसा क्यों काटे", "human_reviewed": null, "final": null, "status": "pending_review", "reviewer": null}
```

### Fields

| Field | Description |
|-------|-------------|
| `audio_file` | Path to audio file (relative to sharepoint_sync/) |
| `stt_model` | Model used for initial transcription |
| `stt_draft` | Initial STT output |
| `human_reviewed` | Corrected transcription by reviewer |
| `final` | Final approved transcription |
| `status` | `pending_review`, `reviewed`, `approved` |
| `reviewer` | Email of reviewer |

### Workflow

1. **STT First Pass**: Run `benchmarking/scripts/generate_initial_transcriptions.py`
2. **Human Review**: Edit `transcriptions.jsonl`, fix errors in `human_reviewed`
3. **Approval**: Set `status` to `approved`, copy `human_reviewed` to `final`

## Notes

- Audio files are NOT committed to git (too large)
- JSONL files ARE committed for tracking and review
