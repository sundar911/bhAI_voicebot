# Contributing to bhAI Voice Bot

Welcome! This guide helps Tiny Miracles team members and developers contribute effectively.

## For Tiny Miracles Team

### Editing Knowledge Base Content

You can directly edit files in `knowledge_base/` without needing to understand the code.

#### What You Can Edit

| Folder | Purpose | Who Should Edit |
|--------|---------|-----------------|
| `knowledge_base/hr_admin/` | Salary, leave, benefits info | HR team |
| `knowledge_base/helpdesk/` | Govt schemes, documents (Aadhaar, PAN, ESIC, etc.) | Helpdesk team |
| `knowledge_base/production/` | Factory floor info | Production team |
| `knowledge_base/shared/` | Company overview, escalation rules | All teams (carefully) |
| `src/bhai/llm/prompts/` | bhAI's personality and conversation rules | Sid / All teams |

Just a loose structure, feel free to change it up completely as you see fit. It just needs to work for further LLM processing.

#### How to Edit

Use **Claude Code** (connected to this GitHub repo). Just tell it what to change:

- *"Update the leave policy in knowledge_base/hr_admin/policies.md to include 10 days maternity leave"*
- *"Add a new section about PF withdrawal to knowledge_base/hr_admin/benefits.md"*

Claude Code will edit the file, create a branch, and open a pull request into `main` for Sundar to review and merge — see [Submitting your changes](#submitting-your-changes) below for the exact steps.

### Editing bhAI's Personality (System Prompt)

bhAI's personality, conversation rules, and tone live in **prompt files** under `src/bhai/llm/prompts/`. These are plain text (markdown) — no coding needed to edit them.

| File | What it controls |
|------|-----------------|
| `prompt_v1_pilot.md` | The active prompt (the only persona prompt) — personality, rules, tone, what to answer, what to defer |
| `use_cases/*.md` | Per-turn blocks injected when a turn is classified as `grievance` / `finance_advice` / `scheme_kb` / `general` |

#### What you can change in the prompt

- How bhAI introduces herself
- Conversation tone and verbal habits
- Which topics bhAI answers vs defers ("मैं पूछ के बताती हूँ")
- Follow-up question style
- Escalation triggers
- Knowledge base usage rules

#### How to edit (same workflow as knowledge base)

Tell Claude Code what you want to change:

- *"Make bhAI ask about the user's family more naturally"*
- *"bhAI should not answer medical questions — always defer to the impact team"*
- *"Change the intro message to mention helpdesk services"*

Claude Code will edit the prompt, create a branch, and open a pull request into `main` for Sundar to review and merge — see [Submitting your changes](#submitting-your-changes) below.

**Important**: `main` branch is protected — all changes require a pull request with at least 1 approval. This prevents accidental prompt changes from going live without review.

#### Writing Guidelines

- Use **simple Hindi** that workers understand
- Keep answers **short** (20-40 seconds when spoken)
- Use **bullet points** for steps
- Include **common questions** workers ask

Example:
```markdown
## Chutti Kaise Le?

1. Team lead ko message karo
2. Reason batao - sick/planned/emergency
3. Jaldi batao, late mat karo

### "Kal nahi aa paungi"
→ Jaldi WhatsApp karo. Reason batao. Calendar me mark hoga.
```

### Submitting your changes

You never edit `main` directly. You make your change on a **branch** and open a **pull request (PR)** — a request for Sundar to pull your change into the live bot. He reviews it, may try it on the test (dev) bot first, then merges. Merging to `main` deploys to the live bot automatically, so you don't deploy anything yourself.

If you're using **Claude Code**, you don't need to memorise any of this — just say *"commit this and open a pull request into main"* and it runs the steps below. They're written out so your Claude (or you) can follow them exactly:

1. Start from the latest `main` and make a new branch:
   ```bash
   git checkout main && git pull
   git checkout -b kb/short-description       # e.g. kb/esic-dispensary-update
   ```
2. Make your edits, then commit them:
   ```bash
   git add <files you changed>
   git commit -m "Update: what you changed"
   ```
3. Push your branch to GitHub:
   ```bash
   git push -u origin kb/short-description
   ```
4. Open a pull request **into `main`**:
   ```bash
   gh pr create --base main --title "Update: what you changed" --body "One or two lines: what and why."
   ```
   No `gh` installed? The `git push` above prints a GitHub link — open it, click **Compare & pull request**, and make sure the base branch is `main`.
5. Send Sundar the PR link. He reviews, tests, and merges.

You **can't** push straight to `main` — it's protected, so every change needs a PR plus one approval. That's the safety net, not a bug.

> Don't have permission to push a branch to this repo? **Fork** it first (GitHub's "Fork" button), push your branch to your fork, and open the PR from your fork into `sundar911/bhAI_voicebot` `main`. Claude Code can do all of this for you.


## For Developers

### Setup

```bash
# Install dependencies
uv sync

# Copy environment file
cp .env.example .env
# Add your API keys

# Run tests
uv run pytest

# Install pre-commit hooks (one-time, blocks bad commits locally)
uv run pre-commit install
```

### Before you commit

Three gates protect `main` from broken code. They run automatically — you don't need to remember them, but knowing what they do helps when one fires:

| Gate | Where it runs | What it catches |
|------|---------------|-----------------|
| `pre-commit` hooks | Local, on every `git commit` | `black`, `isort`, `mypy`, `pytest`, entry-point import smoke |
| GitHub Actions CI | On every push + PR | Same checks as pre-commit, plus a fresh-clone import test |
| Branch protection | At merge time | Requires CI green + 1 PR approval before merging to `main` |

If you've added new behavior (a new endpoint, a new prompt rule, a new integration), invoke `/write-tests` in Claude Code **before committing**. It scans the diff, identifies untested code paths, and proposes tests. Behavior shipped without a test is how regressions sneak in — see [`src/tests/test_contracts.py`](src/tests/test_contracts.py) for examples of regression contracts we maintain for past pilot incidents.

If you absolutely must bypass pre-commit (rare — only when you understand what you're doing):
```bash
git commit --no-verify
```
But CI will still run, and branch protection still blocks merge if CI fails.

### Code Structure

```
src/bhai/
├── config.py                    # Configuration management
├── audio_utils.py               # Audio format conversion
├── stt/                         # Speech-to-text (7 model backends)
│   ├── base.py                  # Abstract STT interface
│   ├── gpu_base.py              # GPU model base class
│   ├── registry.py              # Model registry
│   ├── sarvam_stt.py            # Sarvam saarika (API)
│   ├── sarvam_saaras_stt.py     # Sarvam saaras (API)
│   ├── indic_conformer.py       # IndicConformer (GPU)
│   ├── vaani_whisper.py         # Vaani Whisper (GPU)
│   ├── whisper_large_v3.py      # Whisper Large v3 (GPU)
│   ├── meta_mms.py              # Meta MMS (GPU)
│   └── indic_wav2vec.py         # IndicWav2Vec (GPU)
├── tts/                         # Text-to-speech
│   ├── base.py                  # Abstract TTS interface
│   ├── sarvam_tts.py            # Sarvam AI TTS
│   ├── elevenlabs_tts.py        # ElevenLabs voice cloning
│   └── emotion_tagger.py        # Emotion tagging for TTS
├── llm/                         # Language models
│   ├── base.py                  # Abstract LLM (markdown/COT strip, regex outreach guard)
│   ├── sarvam_llm.py            # Sarvam backend
│   ├── openai_llm.py            # OpenAI backend
│   ├── claude_llm.py            # Anthropic Claude (pilot default)
│   ├── kb_router.py             # Keyword-based KB + use-case router (fallback)
│   ├── llm_router.py            # Claude Sonnet 4.6 KB + use-case router (primary, cached)
│   └── prompts/                 # Prompt templates
│       ├── prompt_v1_pilot.md   # Active persona prompt (the only one — code default)
│       └── use_cases/           # Per-turn injected blocks: grievance, finance_advice, scheme_kb, general
├── escalations/                 # ESCALATE: true → impact-team email
│   └── handler.py               # Per-category routing + Gmail dispatch (docs→Priti/Dinesh/Anu, workplace→Simran, mental_health→Rishi, loan→Priti; Sundar always CC, Anu CC on impact categories)
├── proactive/                   # Brainstorm→critique→tools→draft→judge agent for nudges (v2)
│   ├── thinker.py               # ProactiveThinker — orchestrates the agent loop
│   ├── dossier_loader.py        # Per-user context bundle for the brainstorm pass
│   ├── agent_input.py           # Structures input to each agent pass
│   ├── tools/                   # Tools the agent can call (memory probe, KB lookup, etc.)
│   └── scrubbers/               # PII / safety scrubbers applied to drafts
├── pipelines/                   # Pipeline orchestration
│   ├── base_pipeline.py         # Abstract pipeline
│   └── hr_admin_pipeline.py     # HR-Admin domain pipeline
├── memory/                      # Conversation memory (encrypted)
│   ├── store.py                 # Per-user message persistence
│   └── summarizer.py            # Context window summarization
├── resilience/                  # Reliability (legacy — built for Twilio entry point)
│   ├── faq_cache.py             # FAQ matching (Jaccard) — short-circuit dropped, see ARCHITECTURE §5
│   ├── queue.py                 # Request queue — orphaned under Telegram
│   ├── retry.py                 # Retry with exponential backoff — orphaned
│   └── worker.py                # Background retry worker — orphaned
├── security/                    # Security
│   ├── crypto.py                # Fernet encryption/decryption — active
│   └── webhook_auth.py          # Twilio sig verify — legacy (not used by Telegram)
└── integrations/                # External integrations
    ├── telegram_client.py       # Active: Telegram bot client (sendVoice, getFile, setWebhook)
    ├── email_client.py          # Gmail API client (escalation emails — Railway blocks SMTP)
    ├── twilio_client.py         # Legacy: kept only because resilience/worker.py imports it
    └── sharepoint.py            # SharePoint Graph API
```

### Adding a New STT Backend

1. Create `src/bhai/stt/your_stt.py`
2. Inherit from `BaseSTT`
3. Implement `transcribe()` and `model_name` property
4. Add to benchmarking configs

Example:
```python
from .base import BaseSTT

class YourSTT(BaseSTT):
    def transcribe(self, audio_path: Path) -> Dict[str, Any]:
        # Your implementation
        return {"text": "...", "raw": {...}}

    @property
    def model_name(self) -> str:
        return "your-model-name"
```

### Git Workflow

#### Branches

- `main` - Production-ready code
- `dev` - Integration branch
- `stt/batch-XXX` - STT first-pass branches
- `review/domain-batch-XXX` - Human review branches
- `feature/XXX` - New features

#### Commit Messages

Use clear, descriptive messages:
- `Add: new leave policy content`
- `Fix: STT timeout issue`
- `Update: hr_admin payroll info`
- `Review: corrected batch 001 transcriptions`

### Testing

```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest src/tests/test_config.py

# Run with coverage
uv run pytest --cov=src/bhai

# Run with verbose output
uv run pytest -v
```

Tests live in `src/tests/` (legacy root `tests/` directory was deleted in commit `bb776bd`). 567 tests covering: config, crypto, retry, FAQ cache, memory, LLM base, webhook auth, nudges, Telegram webhook, KB router, LLM router (Sonnet), escalation handler, Sarvam TTS normalization + language detection, behavioral contracts (`test_contracts.py`), and the proactive agent loop (`test_proactive_*` modules — agent_input, dossier, scrubbers, thinker, tools).

### Code Style

- Use Python 3.10+ features
- Type hints for all functions
- Docstrings for public methods
- Format with `black` and `isort`

## Questions?

- Open a GitHub issue for bugs
- Ask in the team Slack for questions
- Check existing docs first
