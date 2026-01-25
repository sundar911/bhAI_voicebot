# Voice Agent PoC (Terminal Only)

Terminal-first proof-of-concept voice agent for Tiny Miracles artisans. Flow: Audio (.wav/.mp3/.m4a) → Sarvam STT (Devanagari) → context-grounded OpenAI response → Sarvam TTS (Manisha) → saved outputs with timings.

## Repo Layout
- `company_context/` — grounding docs (`company_context.md`, `escalation_policy.md`, `style_guide.md`).
- `data/sample_audio/` — place input audio files (empty in repo).
- `scripts/run_demo.py` — CLI runner.
- `src/` — modules (`config.py`, `audio_utils.py`, `sarvam_stt.py`, `llm_openai.py`, `sarvam_tts.py`, `pipeline.py`).
- `outputs/` — created per run (`transcript.txt`, `response.txt`, `response.wav`, `log.json`).
- `.env.example` — copy to `.env` and fill secrets.

## Prerequisites
- Python 3.10+.
- [`uv`](https://docs.astral.sh/uv/) for dependency management.
- System packages:
  - `ffmpeg` (audio conversion, pydub backend).
  - `espeak-ng` (kokoro TTS dependency on some systems).
- Optional: CUDA-capable GPU for faster ASR; auto-detected.

### Install system deps (macOS examples)
```bash
brew install ffmpeg espeak-ng
```

## Setup
```bash
cd voice_poc
cp .env.example .env  # add OPENAI_API_KEY and SARVAM_API_KEY
uv sync
```

`uv sync` will create `uv.lock` and a virtualenv managed by uv.

## Run the demo
```bash
uv run python scripts/run_demo.py --audio data/sample_audio/example.m4a
```
Options:
- `--out_dir outputs/<run_id>` (default: timestamped folder).
- `--openai_model MODEL_NAME` (optional override; default from `.env` or config).
- `--no_tts` (skip TTS; still saves transcript/response/log).

Outputs in the selected `out_dir`:
- `transcript.txt` — ASR text.
- `response.txt` — LLM reply (Hindi, context-grounded).
- `response.wav` — TTS audio unless `--no_tts`.
- `log.json` — stage timings, device info, escalate flag.

## WhatsApp Webhook (Local Test)
1) Set env vars in `.env`:
   - `META_WA_TOKEN`, `META_PHONE_NUMBER_ID`, `META_WABA_ID`, `META_VERIFY_TOKEN`
2) Start the webhook server:
```bash
uv run uvicorn scripts.whatsapp_webhook:app --host 0.0.0.0 --port 8000
```
3) Start ngrok (in another terminal):
```bash
ngrok http 8000
```
4) In Meta App → WhatsApp → Configuration:
   - Callback URL: `https://<ngrok>.ngrok.io/webhook`
   - Verify token: `META_VERIFY_TOKEN`
   - Subscribe to `messages`

## Troubleshooting
- Missing `OPENAI_API_KEY`: set in `.env` or environment.
- ASR slow: CPU-only is expected; if you have GPU ensure CUDA/PyTorch detects it (`torch.cuda.is_available()`).
- Audio issues: ensure ffmpeg installed; unsupported file? Convert to 16k mono wav via script auto-conversion.
- Sarvam errors: check `SARVAM_API_KEY` and URLs in `.env`.
- Network/model download hiccups: rerun after network is stable; transformers/OpenAI downloads cache locally.

## Notes
- Responses stay within company context and will offer escalation when uncertain or if sensitive topics appear. Escalations are marked in `log.json`.
- This PoC is terminal-only; no WhatsApp integration yet.
- Sarvam TTS voice defaults to `manisha`. Change `SARVAM_TTS_VOICE` if needed.

