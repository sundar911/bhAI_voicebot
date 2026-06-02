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

# Escalation emails to impact team (Gmail API — Railway blocks SMTP)
# When ESCALATE: true fires in an LLM response, an email goes out.
# See ARCHITECTURE.md §8 for the per-office routing logic.
GMAIL_CLIENT_ID=...
GMAIL_CLIENT_SECRET=...
GMAIL_REFRESH_TOKEN=...
GMAIL_SENDER_EMAIL=...
ESCALATION_RECIPIENTS=rishi@..., anu@...
ESCALATION_RECIPIENTS_DOCS_BC=priti@...
ESCALATION_RECIPIENTS_DOCS_MIDC=dinesh@...
ESCALATION_ENABLED=true
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
│   ├── tts/               # Text-to-speech (Sarvam bulbul:v3, ElevenLabs)
│   ├── llm/               # Language model backends (Sarvam, OpenAI, Claude)
│   │   ├── prompts/       # Persona prompt + per-use-case blocks (use_cases/)
│   │   ├── llm_router.py  # Sonnet 4.6 KB + use-case classifier (was haiku_router.py)
│   │   └── kb_router.py   # Keyword fallback router
│   ├── proactive/         # Brainstorm→critique→tools→draft→judge agent for nudges
│   ├── escalations/       # ESCALATE: true → Gmail API → impact team
│   ├── pipelines/         # Processing pipelines (base + hr_admin)
│   ├── memory/            # Encrypted store, summarizer, self-edited memory
│   ├── resilience/        # FAQ cache (legacy), retry, worker (Twilio-era)
│   ├── security/          # Encryption (Fernet), webhook auth, rate limiting
│   └── integrations/      # Telegram, Twilio (legacy), SharePoint, email_client
│
├── src/tests/             # Test suite (435 tests, incl. test_contracts.py + test_proactive_*)
│
├── knowledge_base/        # Domain knowledge (editable by TM team)
│   ├── shared/            # Cross-domain (escalation, style)
│   ├── hr_admin/          # HR-specific policies
│   ├── helpdesk/          # Govt docs + schemes (~27 markdown files, Excel source)
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
- **TTS**: Sarvam AI (`bulbul:v3`, suhani voice — auto-detects script and switches between Hindi/Marathi/Tamil/Telugu/Bengali/Punjabi/Gujarati/Kannada/Malayalam/Odia per call) or ElevenLabs (voice cloning)
- **Messaging**: Telegram bot (replaces Twilio/WhatsApp)
- **Security**: Fernet encryption for PII at rest, Telegram secret-token webhook auth
- **Framework**: Python, FastAPI, pydub
- **KB retrieval**: Claude Sonnet 4.6 routes each query to 1-3 helpdesk files + emits a use-case tag (`grievance` / `finance` / `finance_advice` / `scheme_kb` / `general`) for prompt scoping (see [ARCHITECTURE.md §5-6](ARCHITECTURE.md))
- **Escalation**: `ESCALATE: true` from the LLM triggers a Gmail-API email to the impact team, routed per-office (Priti for BC docs, Dinesh for MIDC docs, Rishi+Anu for grievance)
- **Memory**: per-user encrypted SQLite. Background summarizer + Letta-style self-edited memory (LLM emits `<memory>` blocks)
- **Anti-confabulation**: regex backstop on every LLM response detects past-tense / unconsented future-tense outreach claims and re-prompts the model
- **Deployment**: Railway (auto-deploys from `main`, `uv` pinned via `railpack.json`). Data persists on a volume mounted at `/app/data` — see [ARCHITECTURE.md §13](ARCHITECTURE.md#13-deployment--data-persistence).

## License

[Add license information]

## Support

For issues or questions, contact the development team or open a GitHub issue.
