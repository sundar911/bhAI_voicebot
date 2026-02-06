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
Voice Input → STT → LLM (with knowledge base) → TTS → Voice Output
                              ↓
                    [HR-Admin | Helpdesk | Production]
                         knowledge domains
```

## Quick Start

### Prerequisites

- Python 3.10+
- [UV](https://github.com/astral-sh/uv) for dependency management
- ffmpeg for audio processing
- API keys for OpenAI and Sarvam AI

### Installation

```bash
# Clone the repository
git clone https://github.com/your-org/bhAI_voice_bot.git
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
OPENAI_API_KEY=sk-...
SARVAM_API_KEY=...

# Optional
OPENAI_MODEL=gpt-4o-mini
SARVAM_STT_MODEL=saarika:v2.5
SARVAM_TTS_VOICE=manisha
```

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
│   ├── stt/               # Speech-to-text backends
│   ├── tts/               # Text-to-speech backends
│   ├── llm/               # Language model backends
│   ├── pipelines/         # Processing pipelines
│   └── integrations/      # External integrations (WhatsApp)
│
├── knowledge_base/        # Domain knowledge (editable by TM team)
│   ├── shared/            # Cross-domain (escalation, style)
│   └── hr_admin/          # HR-specific policies
│
├── data/                  # Audio data and transcriptions
│   ├── sharepoint_sync/   # Auto-synced audio from SharePoint
│   └── transcription_dataset/  # Ground truth transcriptions
│
├── benchmarking/          # STT model evaluation
│   ├── scripts/           # Benchmark runners
│   └── notebooks/         # Analysis notebooks
│
├── inference/             # Production inference
│   ├── scripts/           # CLI tools
│   └── webhooks/          # WhatsApp integration
│
└── docs/                  # Documentation
```

## For Tiny Miracles Team

### Editing Knowledge Base

The `knowledge_base/` folder contains all the information bhAI uses to answer questions. You can edit these files directly:

1. Open files in VS Code or any text editor
2. Edit the content (keep it in simple Hindi)
3. Save and commit your changes
4. Changes take effect on next restart

See [knowledge_base/README.md](knowledge_base/README.md) for detailed instructions.

### Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on contributing to this project.

## Development

### Running Tests

```bash
uv run pytest
```

### STT Benchmarking

```bash
# Generate initial transcriptions
uv run python benchmarking/scripts/generate_initial_transcriptions.py

# Compute WER after human review
uv run python benchmarking/scripts/compute_wer.py
```

### WhatsApp Integration

```bash
# Start webhook server
uv run uvicorn inference.webhooks.whatsapp_webhook:app --host 0.0.0.0 --port 8000
```

## Tech Stack

- **STT**: Sarvam AI (saarika:v2.5), with benchmarking for IndicWhisper, Vaani Whisper
- **LLM**: OpenAI (gpt-4o-mini)
- **TTS**: Sarvam AI (manisha voice), future: ElevenLabs voice cloning
- **Framework**: Python, FastAPI, pydub

## License

[Add license information]

## Support

For issues or questions, contact the development team or open a GitHub issue.
