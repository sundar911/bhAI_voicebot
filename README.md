# bhAI Voice Bot

A friendly voice assistant for Tiny Miracles employees, providing compassionate support for HR, helpdesk, and production queries in Hindi/Marathi.

## Overview

bhAI is a voice-first assistant that:
- Understands Hindi, Marathi, and Hinglish (code-mixed) speech
- Answers questions about salary, leave, benefits, and workplace policies
- Responds in natural, warm Hindi voice
- Escalates sensitive issues to the human impact team

## Architecture

```
Telegram Voice → STT → LLM (with knowledge base) → TTS → Telegram Voice
                              ↓
                    [HR-Admin | Helpdesk | Production]
                         knowledge domains
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full end-to-end pipeline documentation.

## Quick Start

### Prerequisites

- Python 3.10+
- [UV](https://github.com/astral-sh/uv) for dependency management
- ffmpeg for audio processing
- API keys for Sarvam AI (required), plus OpenAI or Anthropic if using those LLM backends

### Installation

```bash
# Clone the repository
git clone https://github.com/sundar911/bhAI_voicebot.git
cd bhAI_voice_bot

# Install dependencies
uv sync

# Copy and configure environment
cp .env.example .env
# Edit .env with your API keys
```

### Configuration

Create a `.env` file with:

```env
# LLM Backend: "sarvam", "openai", or "claude" (pilot default)
LLM_BACKEND=claude

# Sarvam AI (required for STT/TTS)
SARVAM_API_KEY=...
SARVAM_STT_MODEL=saaras:v3
SARVAM_TTS_MODEL=bulbul:v3
SARVAM_TTS_VOICE=suhani

# Telegram bot (entry point — replaces Twilio/WhatsApp)
TELEGRAM_BOT_TOKEN=...
TELEGRAM_WEBHOOK_SECRET=...

# Claude (default LLM for pilot)
ANTHROPIC_API_KEY=sk-ant-...

# OpenAI (only needed when LLM_BACKEND=openai)
# OPENAI_API_KEY=sk-...

# Encryption (required for conversation memory)
BHAI_ENCRYPTION_KEY=...

# Admin/dashboard auth (default: bhai-pilot-2026)
DASHBOARD_SECRET=...
```

See `.env.example` for all available options.

### Run Demo

```bash
# Process a single audio file
uv run python inference/scripts/run_demo.py --audio path/to/audio.m4a

# Skip TTS output
uv run python inference/scripts/run_demo.py --audio path/to/audio.m4a --no_tts
```

## Project Structure

```
bhAI_voice_bot/
├── src/bhai/              # Core library
│   ├── stt/               # Speech-to-text backends (7 models)
│   ├── tts/               # Text-to-speech (Sarvam, ElevenLabs + emotion tagging)
│   ├── llm/               # Language model backends (Sarvam, OpenAI, Claude)
│   │   └── prompts/       # Prompt templates
│   ├── pipelines/         # Processing pipelines (base + hr_admin)
│   ├── memory/            # Conversation memory (encrypted store + summarizer)
│   ├── resilience/        # FAQ cache, request queue, retry logic, background worker
│   ├── security/          # Encryption (Fernet), webhook auth, rate limiting
│   └── integrations/      # External integrations (WhatsApp, SharePoint)
│
├── src/tests/             # Test suite (79 tests — config, crypto, retry, etc.)
│
├── knowledge_base/        # Domain knowledge (editable by TM team)
│   ├── shared/            # Cross-domain (escalation, style)
│   ├── hr_admin/          # HR-specific policies
│   ├── helpdesk/          # Govt schemes (Aadhaar, PAN, ESIC, etc.)
│   └── users/             # Per-user profiles (gitignored — see ARCHITECTURE.md §13)
│
├── data/                  # Audio data and transcriptions
│   ├── sharepoint_sync/   # Auto-synced audio from SharePoint
│   └── transcription_dataset/  # Ground truth transcriptions
│
├── benchmarking/          # STT model evaluation
│   ├── scripts/           # Benchmark runners and analysis
│   ├── configs/           # Model registry (models.yaml)
│   └── results/           # Comparison CSVs, significance reports
│
├── inference/             # Production inference
│   ├── scripts/           # CLI tools
│   ├── web/               # Dev web chat UI (localhost:8002)
│   └── webhooks/          # Telegram bot entry + nudges loop
│       ├── telegram_webhook.py  # Active entry point
│       ├── nudges.py            # Twice-daily proactive messages
│       └── twilio_webhook.py    # Legacy (Twilio era; not used)
│
├── scripts/               # Utility scripts (SharePoint sync, cleanup, profiles)
│
└── .github/workflows/     # CI (tests, black, isort, mypy)
```

## For Tiny Miracles Team

### Editing the Knowledge Base

The `knowledge_base/` folder contains all the information bhAI uses to answer questions. You edit this using **Claude Code** (connected to this GitHub repo).

Just tell Claude Code what to change. For example:
- *"Update the leave policy in knowledge_base/hr_admin/policies.md"*
- *"Add helpdesk info about Aadhaar card help"*

Claude Code will make the edit, create a branch, and push it. Sundar reviews and approves.

See [knowledge_base/README.md](knowledge_base/README.md) for writing guidelines and file structure.

### Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on contributing to this project.

## Development

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=src/bhai
```

### CI/CD

GitHub Actions runs on every push/PR to `main` and `develop`:
- **test**: pytest + black + isort
- **lint**: mypy type checking

### STT Benchmarking

```bash
# Compare all 7 models across all domains
python3 benchmarking/scripts/compare_models.py

# Statistical significance report
python3 benchmarking/scripts/statistical_significance.py

# Error analysis waterfall
python3 benchmarking/scripts/error_analysis.py --domain helpdesk
```

See [benchmarking/BENCHMARKING.md](benchmarking/BENCHMARKING.md) for full methodology and results.

### Telegram Bot (production entry point)

```bash
# Start the Telegram webhook server locally
uv run uvicorn inference.webhooks.telegram_webhook:app --host 0.0.0.0 --port 8001

# Register the webhook with Telegram (production deploy uses Railway's public URL)
# Pass the X-Telegram-Bot-Api-Secret-Token via TELEGRAM_WEBHOOK_SECRET in .env
```

The bot replaces the old Twilio/WhatsApp integration. See [ARCHITECTURE.md §1](ARCHITECTURE.md#1-webhook-entry-point) for the request flow.

### Dev Web Chat

```bash
# Full voice pipeline in-browser (mic → STT → LLM → TTS → playback)
uv run python inference/web/chat_server.py
# Open http://127.0.0.1:8002
```

## Tech Stack

- **STT**: Sarvam AI (saaras:v3) — statistically validated as best across 7 models on 175 Hindi recordings
- **LLM**: Claude Sonnet (pilot default), Sarvam (sarvam-105b), or OpenAI (gpt-4o-mini) — configurable via `LLM_BACKEND`
- **TTS**: Sarvam AI (`bulbul:v3`, suhani voice) or ElevenLabs (voice cloning)
- **Messaging**: Telegram bot (replaces Twilio/WhatsApp)
- **Security**: Fernet encryption for PII at rest, Telegram secret-token webhook auth
- **Framework**: Python, FastAPI, pydub
- **Deployment**: Railway (auto-deploys from `main`). Data persists on a volume mounted at `/app/data` — see [ARCHITECTURE.md §13](ARCHITECTURE.md#13-deployment--data-persistence).

## License

[Add license information]

## Support

For issues or questions, contact the development team or open a GitHub issue.
