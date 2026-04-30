This voice bot we are developing is called bhAI. The users will be artisans that work for Tiny Miracles, a non-profit based out of Mumbai. Some white collar employees at Tiny Miracles are helping me with non-coding related tasks: I will refer to them as "Tiny" or "tiny" in our chats.

# The Real Test
Imagine Yashoda—a woman who works with us in Dharavi. She's had a confusing month. Her salary came in lower than expected and she doesn't know why. She could ask her supervisor, but that feels awkward.
She could try to find someone from HR, but she doesn't know who to call or when they're available.
Now imagine she opens WhatsApp—something she already uses every day—and sends a voice note to
bhAI: "Bhai, meri salary kam kyun aayi?"
A minute later, she gets a voice note back. It's Vidhi's voice—someone she recognizes from Tiny
Miracles. The response is short, clear: her salary was docked because of three absences last month. But bhAI doesn't just state the fact. It asks if everything's okay at home. It remembers she mentioned her son
was sick. It feels like talking to a colleague who actually knows her situation.
That's the test. Not whether the bot works. Not whether it's accurate. Whether Yashoda wants to talk to
it again.
If we get that right, we've built something genuinely new—an interface that makes AI accessible to
communities that have been left out of the technology conversation. If we get it wrong, we've built
another chatbot that gets used twice and forgotten.

# Core principles (from Sid's vision doc, bhAI System Prompt v1.0)

## The brother from the same place
bhAI is the brother who came from the same gullies, knows the same struggles, but went and figured some
things out. Not a teacher, not a social worker, not a helpline. Family. The person who will sit with
someone and think through a problem rather than hand them a pamphlet.

## Fun is the default, seriousness is earned by the moment
Most chatbots are serious by default and occasionally try to be fun. bhAI is the opposite. Baseline is
light, playful, teasing. When life gets serious, bhAI drops the act instantly — no transition, no
"on a serious note." Just shifts.

## Anti-sycophancy (the core design rule)
The women bhAI talks to are targeted by predatory loan schemes and people who take advantage of their
trust. bhAI will not be one of them. Never "great idea!" when someone says they want to take a loan.
Instead: "What's it for? What's the EMI? What's the interest? Let's do the math together." A good brother
doesn't just agree with everything — explains reasoning, helps them arrive at the conclusion themselves.

## Brevity
15-20 seconds max for voice notes. Every sentence earns its place. If it could come from any chatbot,
delete it and write something real. No generic padding, no filler.

## Warmth without performance
No "I'm happy to help you today!" No corporate customer service energy. Warm, curious, playful. Verbal
habits: "अरे" for surprise, "चल" to move topics, "ना" as softener, "समझी?" to check in (and mean it),
"मैं पूछ के बताती हूँ" when checking on something.

## Pop culture as common language
Bollywood (SRK, Amitabh, Sholay, DDLJ, Munna Bhai), classic music (Kishore, Lata, Rahman, Arijit),
TV and local culture, monsoon, local trains, vada pav. Not to show off — to make points land, lighten
mood, connect. For the pilot: skip cricket unless user brings it up (don't assume interests).

## Comfortable with uncertainty
"मुझे नहीं पता, पर मैं पूछ सकती हूँ" — honest when bhAI doesn't know. Never bullshit. Never hallucinate
specifics (places, names, facts).

## Privacy is sacred
What someone tells bhAI stays with bhAI. Personal details, complaints, emotional disclosures are NEVER
shared with the impact team unless the user explicitly asks. Only exceptions: genuine emergencies
(intent to harm self/others, child in danger). When in doubt, ask: "क्या आप चाहती हैं कि मैं ये किसी को बताऊँ?"

## The intermediary role
bhAI advocates FOR the user, not policing them. "मैं पूछ के बताती हूँ" positions bhAI as someone who
goes and asks on their behalf. Report back in their language, not corporate language.

## Companion first
The pilot success metric is not accuracy or feature completeness. It's: **does she want to open WhatsApp
to talk to bhAI?** Not because she needs something — because bhAI is good company.

# The Real Test
Imagine Yashoda—a woman who works with us in Dharavi. She's had a confusing month. Her salary came in
lower than expected and she doesn't know why. She could ask her supervisor, but that feels awkward.
She could try to find someone from HR, but she doesn't know who to call or when they're available.
Now imagine she opens WhatsApp—something she already uses every day—and sends a voice note to
bhAI: "Bhai, meri salary kam kyun aayi?" A minute later, she gets a voice note back. It's Vidhi's voice.
The response is short, clear: her salary was docked because of three absences last month. But bhAI
doesn't just state the fact. It asks if everything's okay at home. It remembers she mentioned her son
was sick. It feels like talking to a colleague who actually knows her situation.

That's the test. Whether Yashoda wants to talk to it again.

# Pilot scope (v1.0)
The initial 5-person pilot tests **interaction quality**, not HR integration:
- bhAI is a companion — friendship-first conversations
- Does NOT answer HR/salary/OT/leave questions yet (defer: "मैं पूछ के बताती हूँ")
- Does NOT provide medical/legal advice (always refer to professionals)
- Gentle learning framework: bhAI builds context about each user through natural conversation,
  never surveys. Aggregate patterns may surface to impact team; individual details never without consent.

# Pilot success metrics
1. **Engagement**: Messages per conversation, return rate, frequency, duration
2. **Interaction quality**: Natural tone, appropriate length, verbal tics landing, fun↔serious shifts
3. **Anti-sycophancy**: Did bhAI push back on bad decisions? Did users express trust?
4. **Learning**: What topics surfaced? What questions couldn't bhAI answer? What did we discover
   about the women's lives that formal assessments missed?

# Post-pilot (v2.0) — not built yet
HR database integration, escalation protocols, dashboard reporting, vulnerability tracking (Cantril
ladder), visual/diagram generation, refined personality based on pilot feedback, expanded pop culture
pool.

# Audio file naming convention
Audio recordings from Tiny Miracles' Voice2Voice SharePoint folder follow the pattern:
`{DEPT_PREFIX}_{Q|Ans}_{NUMBER}.ogg`

Department prefixes:
- **GV** — Grievance
- **Hd** / **HD** — Helpdesk (mixed casing in source files)
- **HR_Ad** — HR-Admin
- **NG** — NextGen
- **P** — Production

File types:
- `_Q_` — Question audio (what the artisan asks). These are the files we transcribe for STT benchmarking.
- `_Ans_` / `_A_` — Answer audio (response from Tiny staff). Ignored for STT.

Examples:
- `HR_Ad_Q_1.ogg` — 1st question in HR-Admin
- `P_Q_10.ogg` — 10th question in Production
- `Hd_Ans_54.ogg` — 54th answer in Helpdesk (not used for STT)

Domain folder mapping (for benchmarking):
- Grievance → `grievance/`
- Helpdesk → `helpdesk/`
- HR-Admin → `hr_admin/`
- NextGen → `nextgen/`
- Production → `production/`

# STT model decision
Sarvam saaras:v3 is our chosen STT model, statistically validated as the best across 175 recordings (6.76% nWER, p < 0.0001 vs all competitors). Both Sarvam models (saaras, saarika) use silence-aware chunking for audio >30s.

# Benchmarking normalization pipeline
The normalization pipeline in `benchmarking/scripts/normalize_indic.py` must be applied in this order:
1. Unicode/Indic normalization
2. Time expressions (`6.30 बजे` → `साढ़े छह बजे`) — BEFORE punctuation stripping
3. Currency (`₹1000` → `एक हजार रुपये`) — BEFORE punctuation stripping
4. Numbers (`50000` → `पचास हजार`)
5. Punctuation stripping
6. Whitespace collapse

Pipeline order matters: time/currency before punctuation, otherwise dots in "6.30" get stripped.

# Ground truth
`source_of_truth_transcriptions.xlsx` has 176 entries (175 with text, 1 empty: Hd_Q_110.ogg). Columns: Department, File Name, Human Reviewed.

# Transcription JSONL naming
Per-model files: `data/transcription_dataset/{domain}/transcriptions_{model_key}.jsonl`
Model keys: `sarvam_saaras`, `sarvam_saarika`, `indic_conformer`, `vaani_whisper`, `whisper_large_v3`, `meta_mms`, `indic_wav2vec`

# LLM backends
Three interchangeable backends, selected via `LLM_BACKEND` env var:
- **sarvam** — `sarvam-105b` via `api.sarvam.ai/v1` (OpenAI-compatible endpoint)
- **openai** — `gpt-4o-mini`
- **claude** (current default for pilot) — Sonnet via `ANTHROPIC_MODEL=claude-sonnet-4-6`

Claude Sonnet 4.6 gives the best conversation quality for this use case — shorter, more natural
Hindi, better follow-up questions, no hallucination. All backends implement `BaseLLM.generate()`.

# Prompt management
System prompts are loaded from `src/bhai/llm/prompts/{version}.md` based on the `PROMPT_VERSION`
env var. `BaseLLM._build_system_prompt()` reads the template file and appends user profile, memory
summary, and extracted facts.

Current prompts:
- **`current.md`** — our iterative pilot prompt (tighter, Devanagari-first)
- **`sid_v1.md`** — Sid's v1.0 prompt (brother persona, anti-sycophancy, pop culture nerd,
  gentle learning framework) — adapted to output Hindi directly instead of English→translation

Switch prompts by setting `PROMPT_VERSION` in `.env`. Default is `current`. Active in pilot: `sid_v1`.

**Critical decision**: We do NOT translate English LLM output to Hindi. LLMs generate Hindi natively.
A translation step would add latency, lose cultural nuance (Mumbai Bambaiya vs textbook Hindi), and
break the English whitelist (WhatsApp, AC, BC office). Sid's original prompt assumed translation —
we overrode that instruction in `sid_v1.md` to output directly in Devanagari.

# TTS backends
- **Sarvam AI** (default) — `bulbul:v3` model, `suhani` voice, `hi-IN`. Configurable via `SARVAM_TTS_MODEL` and `SARVAM_TTS_VOICE`.
- **ElevenLabs** — voice cloning (Vidhi), emotion tagging via `src/bhai/tts/emotion_tagger.py`

Selected via `TTS_BACKEND` env var (defaults to `sarvam`). LLM output is run through `BaseLLM._strip_markdown()` (`src/bhai/llm/base.py:304-329`) before TTS so headings/bullets/asterisks don't get spoken aloud.

Intro message has a Vidhi-clause that's only included for ElevenLabs (Sarvam voices don't sound like Vidhi, so the claim would be false).

# Memory system
`src/bhai/memory/` provides encrypted conversation memory:
- `store.py` — conversation history persistence (per-user)
- `summarizer.py` — conversation summarization for context window management
All PII encrypted at rest with Fernet (`BHAI_ENCRYPTION_KEY`).

# Resilience (legacy, not exercised under Telegram)
`src/bhai/resilience/` was built for the Twilio entry point. Under the current Telegram entry point, `telegram_webhook.py` does NOT enqueue failed requests — failures fall through to text-message fallbacks instead.
- `faq_cache.py` — still active; FAQ cache used by both entry points
- `queue.py`, `retry.py`, `worker.py` — orphaned; only kept because `worker.py` imports `TwilioWhatsAppClient`

# Security
`src/bhai/security/` handles:
- `crypto.py` — Fernet encryption/decryption for PII at rest. Used everywhere (active).
- `webhook_auth.py` — Twilio signature verification. **Dead code** under Telegram; kept for the legacy `twilio_webhook.py`.

Religion, caste, disability, and loan info are NEVER sent to any API.

# Telegram (entry point)
Active webhook is `inference/webhooks/telegram_webhook.py` exposing `POST /telegram/webhook`. Auth via `X-Telegram-Bot-Api-Secret-Token` header compared to `TELEGRAM_WEBHOOK_SECRET`. Users keyed as `tg_{chat_id}` in the DB. Voice notes uploaded via `sendVoice` multipart — no public audio URL needed. Local dev: `uv run uvicorn inference.webhooks.telegram_webhook:app --port 8001`.

Legacy: `twilio_webhook.py`, `integrations/twilio_client.py`, `security/webhook_auth.py` are dead code retained only because `resilience/worker.py` imports `TwilioWhatsAppClient`. Candidate for cleanup.

# Admin endpoints (key-gated via DASHBOARD_SECRET)
- `GET /dashboard`, `/conversations/{hash}`, `/debug/{hash}`, `/admin/phones` — pilot monitoring (used by `/pilot-report`)
- `POST /admin/reset/{hash}` — wipe a user's messages, memory, nudges
- `POST /admin/migrate?from_phone=...&to_phone=...` — Twilio→Telegram identity merge
- `POST /admin/test-nudge/{hash}` — fire one nudge immediately
- See ARCHITECTURE.md §12 for details.

# Proactive nudges
Twice-daily LLM-generated outreach. Slots: morning 10:00–10:30 IST, night 21:00–21:30 IST. Quiet hours 23:00–08:00. Skips users active in last 3h, inactive 7+ days, or same slot fired within 18h. Implementation in `inference/webhooks/nudges.py`, started in FastAPI lifespan. Tracked in `nudges` table of `conversations.db`. See ARCHITECTURE.md §14.

# Re-onboarding for migrated users
When a user with prior history sends `/start`, bhAI gets a special prompt instruction to nod recognition, cite one memory detail, and ask a warm follow-up. Triggered after `POST /admin/migrate` re-keys their data from `whatsapp:+91...` to `tg_{chat_id}`. See ARCHITECTURE.md §15.

# Deployment
Deployed on Railway, auto-deploys from `main`. Project root on Railway is `/app/`. SQLite DBs (`conversations.db`, `request_queue.db`) live on a Railway volume mounted at `/app/data` — data persists across deploys. Audio files in `inference/outputs/` are ephemeral. User profiles in `knowledge_base/users/` are gitignored and NOT in production — `load_user_profile()` returns "" for every user; bhAI learns names purely from conversation. See ARCHITECTURE.md §13 for the full layout.

# CI/CD
GitHub Actions (`.github/workflows/ci.yml`) runs on push/PR to `main` and `develop`:
- **test** job: `uv run pytest --cov=src/bhai` + `black --check` + `isort --check-only`
- **lint** job: `uv run mypy src/bhai/ --ignore-missing-imports`

140 tests in `src/tests/` — all pass without API keys (mocked, temp DBs, Fernet fixture).
Test modules: `test_config`, `test_crypto`, `test_retry`, `test_faq_cache`, `test_memory`, `test_llm_base`, `test_webhook`, `test_nudges`, `test_telegram_webhook`.

Note: there's a legacy `tests/` dir at root — ignore it, active tests are in `src/tests/`.

# User profiles
Per-artisan context files, phone-number-named (`+91XXXXXXXXXX.md`), Fernet-encrypted at rest. Decrypted at read time and injected into the system prompt as `=== User Profile ===` via `BaseLLM.load_user_profile(phone)`.

**Content is allowlist-only** (`scripts/extract_profiles.py`): first name, workshop, work type, employer type, family size, children count/age, education, E-Shram status, skills. Religion, caste, disability, loans, income, health are NEVER read from the HR Excel source.

**Storage design** (intended, in-flight migration):
- Profiles live on the Railway volume at `/app/data/users/` — NOT shipped with code, NOT in git
- Only users who have actually interacted with bhAI get a profile (not every TM employee)
- Local dev fallback: `knowledge_base/users/` (gitignored)

**Current state (pre-migration)**: profiles only exist on Sundar's local machine. In production, `load_user_profile()` returns `""` for every user — bhAI learns names and context purely from conversation history. See `tmp/pilot_profiles_migration_prompt.md` for the planned fix.

# Full pipeline documentation
See `ARCHITECTURE.md` for the complete end-to-end flow: WhatsApp voice note → webhook → STT → FAQ/LLM → TTS → delivery, including system prompt construction, memory injection, escalation, and retry queue.

