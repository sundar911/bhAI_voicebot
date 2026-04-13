# bhAI Architecture Guide

How a WhatsApp voice note becomes a voice response. This document traces the full pipeline end-to-end.

For core design principles and personality, see [CLAUDE.md](CLAUDE.md).
For setup and project structure, see [README.md](README.md).

---

## Pipeline Overview

```
WhatsApp Voice Note
       │
  ┌────▼─────────────────────────────────┐
  │  POST /webhook (Twilio)              │
  │  Signature verify → Rate limit       │
  │  Return empty TwiML immediately      │
  └────┬─────────────────────────────────┘
       │ BackgroundTask
  ┌────▼─────────────────────────────────┐
  │  process_message()                   │
  │                                      │
  │  1. Session management               │
  │  2. STT (Sarvam saaras:v3)           │
  │  3. Greeting detection (onboarding)  │
  │  4. FAQ cache check                  │
  │  5. LLM generation (if no cache hit) │
  │  6. Save messages + summarize        │
  │  7. TTS → audio file                 │
  │  8. Twilio send audio URL            │
  └──────────────────────────────────────┘

  On failure at STT or LLM:
  ┌──────────────────────────────────────┐
  │  RequestQueue (SQLite)               │
  │  RetryWorker polls every 30s         │
  │  Resumes from saved stage            │
  └──────────────────────────────────────┘
```

All code paths live in `inference/webhooks/twilio_webhook.py`.

---

## 1. Webhook Entry Point

**`POST /webhook`** — `twilio_webhook.py:442`

1. **Signature verification**: Twilio `X-Twilio-Signature` header validated via `verify_twilio_signature()` (`src/bhai/security/webhook_auth.py`). Rejects forged requests with 403.
2. **Extract fields**: `From` (sender), `NumMedia`, `MediaUrl0`, `MediaContentType0`, `Body`.
3. **Phone hash**: `_phone_hash()` — SHA256 first 12 chars, used in all logs instead of real number.
4. **Rate limit**: `_check_rate_limit()` — 10 requests per 60 seconds per user, in-memory sliding window.
5. **Message type**: Audio if `NumMedia > 0` and content type contains "audio" or "ogg". Text if `Body` present.
6. **Dispatch**: `process_message()` added as FastAPI `BackgroundTask`. Webhook returns empty TwiML immediately so Twilio doesn't retry.

---

## 2. Session Management

**`ConversationStore.get_or_create_session()`** — `src/bhai/memory/store.py:86`

- Looks up last message timestamp for this phone number
- **New session** if: no prior messages, OR gap > 4 hours (`SESSION_GAP_HOURS`)
- Session ID: random UUID (12 hex chars), stored with every message
- All timestamps in IST
- `is_first_ever_message()`: true if zero prior user messages (triggers onboarding)

---

## 3. Speech-to-Text

**`SarvamSTT.transcribe()`** — `src/bhai/stt/sarvam_stt.py`

- Model: Sarvam saaras:v3 (6.76% nWER, validated across 175 recordings — see `benchmarking/BENCHMARKING.md`)
- Audio downloaded from Twilio CDN via `TwilioWhatsAppClient.download_media()`
- Silence-aware chunking for audio >30 seconds
- Output: `{"text": "...", "raw": {...}}`

**On failure**: Request queued at `stage="stt"`, user gets Hindi fallback text:
> "Sun nahi paayi, thodi der mein phir try karti hoon."

---

## 4. Onboarding Flow

**First-ever message handling** — `twilio_webhook.py:286-350`

Two branches:

| Condition | Action |
|-----------|--------|
| First-ever + greeting word (hi, hello, namaste...) | Skip FAQ + LLM entirely, send `_INTRO_TEMPLATE` directly |
| First-ever + real question | Run through LLM normally, **append** intro text after the answer |

The intro introduces bhAI:
> "Are hay! Main bhAI hoon — Vidhi ki awaaz mein bolti hoon par Vidhi nahi hoon..."

Greeting detection: `_detect_greeting()` checks if message is short (<50 chars) and first word is in `_GREETING_WORDS`.

---

## 5. FAQ Cache

**`FAQCache.match()`** — `src/bhai/resilience/faq_cache.py`

- Parses `## Common Questions` sections from all knowledge base markdown files at startup
- Matching: tokenizes transcript and each FAQ question, computes **Jaccard similarity** on token sets
- Threshold: `config.faq_cache_threshold` (default 0.6)
- **Hit**: Bypass LLM entirely, return cached answer + closure ("Aur kuch poochna hai?")
- **Miss**: Fall through to LLM generation

This is the fast path — no API call needed for common questions.

---

## 6. System Prompt Construction

This is the core of how bhAI thinks. Built by `BaseLLM._build_system_prompt()` in `src/bhai/llm/base.py:130`.

### What the LLM receives

```
System Prompt:
┌─────────────────────────────────────────────────────┐
│  Prompt Template (current.md or prompt_v1_pilot.md) │  ← persona, rules, tone
│  + === User Profile ===                     │  ← from knowledge_base/users/{phone}.md
│  + === Memory Summary ===                   │  ← rolling 3-4 line Hindi summary
│  + === Remembered Facts ===                 │  ← bullet list of key details
│  + === Emotion Annotation ===               │  ← EMOTIONS_JSON format instruction
└─────────────────────────────────────────────┘

User Message:
┌─────────────────────────────────────────────┐
│  === Recent Conversation === (last 8 msgs)  │
│  [Topic-switch suggestion if 6+ turns]      │
│  (New session flag if applicable)           │
│  "User ka voice message (Hindi/Marathi)..." │
│  User: {transcript}                         │
└─────────────────────────────────────────────┘
```

### Prompt versions

Selected via `PROMPT_VERSION` env var, loaded from `src/bhai/llm/prompts/{version}.md`.

| Version | File | Persona |
|---------|------|---------|
| `current` (default) | `current.md` | Casual friend. Extraverted, conversational. Devanagari-first. |
| `prompt_v1_pilot` | `prompt_v1_pilot.md` | Pilot prompt (Sonnet-optimized). Brother persona, anti-sycophancy, KB-strict rules, helpdesk-first mode. |

Templates are cached after first load (`BaseLLM._prompt_cache`).

### Shared knowledge (always loaded at init)

Three files from `knowledge_base/shared/` are loaded in `BaseLLM.__init__()`:

| File | Purpose |
|------|---------|
| `company_overview.md` | Tiny Miracles mission, workshops, work hours, attendance rules |
| `style_guide.md` | Tone, length targets (20-40s), structure, what to avoid |
| `escalation_policy.md` | When to set `ESCALATE: true` (health, DV, self-harm, etc.) |

### Per-user context

- **User profile**: `knowledge_base/users/{phone}.md` — Fernet-encrypted at rest, decrypted at load time. Contains name, department, family, personality notes.
- **Memory summary**: Rolling 3-4 line Hindi summary of past conversations.
- **Extracted facts**: Bullet list of remembered details (name, family, preferences).

### Topic tracking

`BaseLLM._TOPIC_KEYWORDS` (line 156) maps 7 topic categories to Hindi/English keywords:
khana, Mumbai, kaam, mausam, Bollywood, parivaar, zindagi.

If the same topic is detected for 6+ consecutive turns, a Hindi suggestion is injected into the user message prompting a smooth topic switch. Transition map in `_TOPIC_TRANSITIONS` (line 210).

### Emotion annotation

When using `generate_with_emotions()`, the system prompt includes `EMOTION_INSTRUCTION` requesting:
```
EMOTIONS_JSON: [{"text": "segment text", "emotion": "neutral"}, ...]
```
Valid emotions: `excited`, `whisper`, `sigh`, `sad`, `laugh`, `pause`, `neutral`.

Used by ElevenLabs TTS for voice modulation. Sarvam TTS ignores emotions.

---

## 7. LLM Backends

**`create_llm()`** — `src/bhai/llm/__init__.py`

Selected via `LLM_BACKEND` env var:

| Backend | Class | Model |
|---------|-------|-------|
| `sarvam` | `SarvamLLM` | `sarvam-105b` via OpenAI-compatible API |
| `openai` | `OpenAILLM` | `gpt-4o-mini` |
| `claude` (pilot default) | `ClaudeLLM` | Configurable via `ANTHROPIC_MODEL` env var (default: `claude-haiku-4-5-20251001`, pilot uses Sonnet) |

All inherit from `BaseLLM` and only implement `_call_api()` + `model_name`.

API calls go through `_call_api_with_retry()` — 3 attempts, exponential backoff (1s base, 10s max) via `retry_with_backoff()`.

### Response parsing

1. **Escalation**: `_detect_escalation()` looks for `ESCALATE: true/false` line
2. **Cleanup**: `_clean_response()` strips ESCALATE and EMOTIONS_JSON lines
3. **Emotions**: `_parse_emotion_segments()` extracts and validates the JSON array

**On LLM failure**: Request queued at `stage="llm"` with transcript saved. No user notification (voice-only mode — they'll get the response when retry succeeds).

---

## 8. Escalation

Categories that trigger `ESCALATE: true` (from `escalation_policy.md`):
- Health emergencies (injury, pregnancy, sick child)
- Domestic violence or safety threats
- Self-harm or extreme distress
- Workplace harassment or bullying
- Financial crisis (eviction, medical bills)
- Legal issues
- User asks to speak with a human

When detected: response still sent to user, flag logged. Human notification to impact team is future work.

---

## 9. Memory & Summarization

### Conversation Store
**`ConversationStore`** — `src/bhai/memory/store.py`

- Backend: SQLite (`data/conversations.db`) with WAL journal mode
- Tables: `messages` (per-message, encrypted content) and `memory` (per-user rolling summary)
- All PII columns (`content_enc`, `summary_enc`, `facts_enc`) encrypted with Fernet

Every user and assistant message is saved via `save_message()`.

### Summarization
**`src/bhai/memory/summarizer.py`**

- **Trigger**: Every 5 user messages (`SUMMARIZE_EVERY_N = 5`)
- **Flow**: `build_summarize_request(old_summary, recent_10_messages)` → LLM call → `parse_summary()` extracts SUMMARY and FACTS blocks → `merge_facts()` deduplicates
- **Prompt**: Hindi instruction asking for 3-4 line summary + fact list (names, family, work, health, preferences)
- **Non-critical**: Failures are logged but never block the response

---

## 10. TTS & Delivery

### Text-to-Speech

Selected via `TTS_BACKEND` env var:

| Backend | Voice | Flow |
|---------|-------|------|
| `sarvam` (default) | manisha (hi-IN) | API → WAV → `convert_to_ogg_opus()` |
| `elevenlabs` | Vidhi's cloned voice | API → MP3 → OGG Opus. Supports `synthesize_with_emotions(segments)` |

Emotion tags from `src/bhai/tts/emotion_tagger.py` map to ElevenLabs SSML-like annotations (e.g., `excited` → `[excited]`).

### Audio serving

`GET /audio/{filename}` — `twilio_webhook.py:182`
- Serves from `inference/outputs/twilio_audio/`
- Path traversal protection: resolves and validates against serve directory
- Returns `audio/ogg` FileResponse

### Delivery to WhatsApp

```python
twilio_client.send_audio_message(to_number=sender, media_url=audio_public_url)
```
- `audio_public_url` = `{BASE_URL}/audio/{filename}` (BASE_URL is typically an ngrok URL)
- Twilio fetches the audio from our server and delivers it as a WhatsApp voice note

**On TTS failure**: Silent degradation — no text fallback in main path (user may retry). The retry worker's TTS path does fall back to text.

---

## 11. Resilience: Queue & Retry Worker

### Request Queue
**`RequestQueue`** — `src/bhai/resilience/queue.py`

- Backend: SQLite (`data/request_queue.db`)
- Stores: phone, sender, audio_path, stage, transcript, llm_response, domain, attempt count
- Backoff: `30s * 2^attempt`, capped at 30 minutes
- Dead after: max attempts exceeded OR request age > 23 hours (Twilio's WhatsApp message window)

### Retry Worker
**`RetryWorker`** — `src/bhai/resilience/worker.py`

```
Worker Loop (every 30s):
  dequeue_ready() → pick one pending request
       │
       ├─ stage="stt"  → transcribe → update to "llm" stage
       ├─ stage="llm"  → generate → update to "tts" stage
       └─ stage="tts"  → synthesize → send via Twilio
                              (text fallback if TTS fails)
       │
  ┌────▼──────────────┐
  │ mark_completed()   │  success
  │ mark_failed()      │  failure → re-queue with backoff
  │ send APOLOGY_TEXT  │  dead → Hindi apology to user
  └────────────────────┘
```

- Started as an asyncio task in FastAPI lifespan (`twilio_webhook.py:158`)
- Cleans up completed entries older than 48 hours
- Apology text: "Maaf karo, abhi kuch problem ho rahi hai. Thodi der mein phir se try karo ya apne supervisor ko call karo."

---

## Error Handling Summary

| Stage | Failure Behavior | User Experience |
|-------|------------------|-----------------|
| Signature verify | 403 Forbidden | Nothing (spoofed request) |
| Rate limit | Empty TwiML | Message silently dropped |
| Media download | Text fallback | "Sun nahi paayi, phir se voice note bhejo." |
| STT | Queue retry + text | "Sun nahi paayi, thodi der mein phir try karti hoon." |
| LLM | Queue retry, silent | No response (retried in background) |
| TTS | Silent degradation | No response (retry worker sends text fallback) |
| Dead request | Apology text | Hindi apology via text message |

---

## Related Docs

- [CLAUDE.md](CLAUDE.md) — Core principles, personality, component reference
- [README.md](README.md) — Setup, configuration, project structure
- [CONTRIBUTING.md](CONTRIBUTING.md) — Development workflow, code structure
- [knowledge_base/README.md](knowledge_base/README.md) — Editing guidelines for Tiny team
- [benchmarking/BENCHMARKING.md](benchmarking/BENCHMARKING.md) — STT model evaluation
