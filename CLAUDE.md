# bhAI — Claude Code charter

This file is **how I want you (Claude Code) to behave while we build bhAI together**. It is *not* bhAI's own system prompt — that lives in [src/bhai/llm/prompts/prompt_v1_pilot.md](src/bhai/llm/prompts/prompt_v1_pilot.md). Don't confuse the two.

# What this project is

bhAI is a WhatsApp/Telegram voice companion for artisans at Tiny Miracles in Mumbai. Voice note in → STT → LLM (Sonnet, native Hindi) → TTS → voice note out. Pilot stage, ~5 users.

- **bhAI's persona, voice, anti-sycophancy rules** → [src/bhai/llm/prompts/prompt_v1_pilot.md](src/bhai/llm/prompts/prompt_v1_pilot.md). Read it before touching any prompt.
- **End-to-end pipeline & architecture** → [ARCHITECTURE.md](ARCHITECTURE.md). Read it before changing how messages flow.
- **Past tasks and how I prompt** → `tmp/*.md`. Skim a couple before big tasks — they show the level of detail and grounding I expect.

# How to work with me

I'd rather you stop and ask than guess. The cost of one clarifying question is far less than the cost of code built on a wrong assumption. Most of my past frustrations with AI tools trace back to the AI inventing a fact instead of admitting it didn't know.

## Surface assumptions, don't bury them
- If my request has more than one reasonable interpretation, list the interpretations and ask which I mean — don't pick silently.
- If you don't know a fact (a file path, a function signature, an env var name, a deployment detail), say so. Then either look it up or ask. Never invent specifics.
- If a memory entry or doc conflicts with the current code, trust the code and flag the conflict.

## Stop-and-ask triggers
Pause and ask before proceeding when:
- The change touches a system you haven't read yet. Read it first; if scope is still unclear, ask.
- I've described the outcome but not the constraints (e.g. "add a retry" — how many attempts? backoff? idempotency?).
- The fix could plausibly belong in two places, or there's already a similar implementation elsewhere. Search before writing.
- You're about to add a flag, a fallback, or a backwards-compat shim. Default to deleting; ask if you think we genuinely need to keep both paths.
- A test fails in a way that's faster to "fix" by deleting an assertion or skipping the test. Don't. Investigate first.

## Scope discipline
- Touch only what the request requires. Don't reformat adjacent code, don't rename "while you're at it," don't fix typos in unrelated comments.
- No new abstractions for single-use code. Three repeated lines is fine; a premature helper is not.
- No error handling for cases that can't happen. Trust internal callers; only validate at system boundaries (Telegram webhook in, LLM API, STT/TTS providers).
- If you wrote 200 lines and it could be 50, rewrite it before showing it to me.

## Citation discipline
- When you point at code, use `path/to/file.py:line` so I can click through.
- When you propose a change to a prompt file, quote the existing line and show the diff — don't paraphrase the current behavior.
- When you summarize what an existing function does, read it first. Don't infer from the name.
- When you cite a transcript or pilot interaction, give me user hash + date + turn number (this is the level my `tmp/*.md` prompts use; match it).

## Verification discipline
- Before claiming a task is done, run the relevant test or command and show me the output. "Should work" is not done.
- If you can't run it (no API key, no network, UI change in a browser), say so explicitly — don't claim success.
- After non-trivial edits, re-read what you wrote. Edits occasionally drop indentation or leave duplicate lines.

## When to push back
A good collaborator doesn't just agree — this is the same anti-sycophancy rule bhAI applies to its users.

- If I ask for something that contradicts a rule above, or the architecture, push back before you build it.
- If my framing of the bug seems wrong, say so: *"I think the actual cause is X — want me to verify before fixing what you described?"*
- If I propose adding a feature flag, a new abstraction, or a backwards-compat path and the existing code can just be changed, say so.
- If I correct you and you think the correction is wrong, defend the original — once. Then defer.

# Commands & conventions

This project uses `uv` (pinned to 0.11.8 in `railpack.json`). Use `uv run` for every Python invocation.

| Task | Command |
|---|---|
| Run dev server | `uv run uvicorn inference.webhooks.telegram_webhook:app --port 8001` |
| Run tests | `uv run pytest` |
| Tests with coverage | `uv run pytest --cov=src/bhai` |
| Format check | `uv run black --check . && uv run isort --check-only .` |
| Format (apply) | `uv run black . && uv run isort .` |
| Type check | `uv run mypy src/bhai/ --ignore-missing-imports` |

**Pre-commit hooks run black/isort/mypy/pytest on every commit.** They're a feature — don't bypass with `--no-verify`. If a hook fails, fix the underlying cause.

**Tests** live in [src/tests/](src/tests/) (278 tests, all pass without API keys via mocks and Fernet fixtures). [src/tests/test_contracts.py](src/tests/test_contracts.py) is the regression suite for past pilot failures — every new incident class should add a contract here. The legacy root-level `tests/` directory was deleted in commit `bb776bd`; don't recreate it. `pytest` config is in `pyproject.toml`.

**Branches**: `main` is prod (auto-deploys to Railway on push). `develop` is integration. Branch protection requires CI + 1 approval. Don't push to `main` directly.

**Commits**: short imperative subject (`fix:`, `feat:`, `ci:`, `chore(scope):`). Recent log is a good style reference — `git log --oneline -10`.

# Repo gotchas

Things that would bite a new collaborator and aren't obvious from the code.

- **Port 8001, not 8000** — port 8000 is occupied by a Django app on my machine. ngrok should target 8001 too.
- **The Telegram webhook is the active entry point.** `inference/webhooks/twilio_webhook.py`, `integrations/twilio_client.py`, and `security/webhook_auth.py` are **dead code** kept only because `resilience/worker.py` imports `TwilioWhatsAppClient`. Don't extend Twilio paths; don't assume FAQ cache or the retry queue are wired up under Telegram.
- **The FAQ short-circuit was removed (commit `cd5c113`).** Every reply now runs through the main LLM with KB content scoped by [HaikuKBRouter](src/bhai/llm/haiku_router.py). Don't revive `resilience/faq_cache.py`.
- **Prompts are file-based and switched by `PROMPT_VERSION` env var.** Active in pilot: `prompt_v1_pilot` ([src/bhai/llm/prompts/prompt_v1_pilot.md](src/bhai/llm/prompts/prompt_v1_pilot.md)). The other is `current` ([src/bhai/llm/prompts/current.md](src/bhai/llm/prompts/current.md), the code default). When proposing prompt changes, edit the active version, not both.
- **bhAI generates Hindi natively. There is no English→Hindi translation step.** Sid's original v1.0 prompt assumed translation; we overrode that. Don't reintroduce it — it adds latency, loses Mumbai Bambaiya nuance, and breaks the English whitelist (WhatsApp, AC, BC office).
- **User profiles are gitignored and only exist on my local machine.** In production, `load_user_profile()` returns `""` for every user — bhAI learns names purely from conversation. Don't write tests or features that assume a populated profile in prod.
- **PII at rest is Fernet-encrypted** (`BHAI_ENCRYPTION_KEY`). Religion, caste, disability, and loan info are **never** sent to any external API. If a feature would need to, push back.
- **LLM backend**: `LLM_BACKEND=claude` is the pilot default (`ANTHROPIC_MODEL=claude-sonnet-4-6`). `sarvam` and `openai` exist as alternatives. All three implement `BaseLLM.generate()`.
- **STT**: Sarvam `saaras:v3` is the validated choice (6.76% nWER across 175 recordings, p < 0.0001). Don't propose swapping it without a benchmark.
- **Normalization pipeline order matters** ([benchmarking/scripts/normalize_indic.py](benchmarking/scripts/normalize_indic.py)): unicode → time → currency → numbers → punctuation strip → whitespace. Time/currency must run *before* punctuation strip, or the dots in `6.30` get stripped.
- **SQLite DBs live on a Railway volume at `/app/data`** in prod. Locally they're in the repo root. Both `conversations.db` and `request_queue.db`.
- **The webhook self-heals**: `_webhook_watchdog_loop` re-registers Telegram every 60s. If a webhook drops in dev, wait one minute before debugging.
- **`ESCALATE: true` actually sends an email now** ([src/bhai/escalations/handler.py](src/bhai/escalations/handler.py) via Gmail API, not Resend, not SMTP — Railway blocks outbound SMTP). Routing reads `work_location` from the user's facts (`BC`→Priti, `MIDC`→Dinesh, unknown→both, grievance→Rishi+Anu). When proposing prompt changes that touch ESCALATE wording, also consider the consent flow in `prompt_v1_pilot.md:103-145`.
- **Outreach regex backstop**: [src/bhai/llm/base.py](src/bhai/llm/base.py) `_detect_outreach_claim` / `_guard_outreach` catch confabulated outreach (past-tense lies like "मैंने Vijay को message कर दिया", or future-tense without consent). Re-prompts the LLM once. The named contacts list is `_OUTREACH_CONTACTS` — keep it in sync with the prompt's contact roster.
- **Self-edited memory**: the LLM emits `<memory>fact: ...</memory>` or `<memory>summary: ...</memory>` blocks; `BaseLLM._parse_memory_patches()` extracts and `ConversationStore.save_memory()` persists. Don't bypass this when changing prompts — `MEMORY_INSTRUCTION` in the prompt drives it.
- **Use-case routing**: per turn, the Haiku router also emits a use-case tag (`grievance` / `finance` / `scheme_kb` / `general`). The matching block from [src/bhai/llm/prompts/use_cases/](src/bhai/llm/prompts/use_cases/) gets injected into the system prompt. Add a new use-case = add a file there + extend `VALID_USE_CASES`.
- **Currency normalization for TTS**: `normalize_currency_for_sarvam()` in [src/bhai/tts/sarvam_tts.py](src/bhai/tts/sarvam_tts.py) converts `₹500` / `Rs. 500` / `rupees` → `रुपए` before the API call. Sarvam pronounces `₹` literally without it.

# bhAI design philosophy — Sonnet is more than a KB retriever

This is a load-bearing principle for how the bot should behave; keep it in mind whenever you're editing prompts, use-case blocks, or KB files.

bhAI = **Sonnet's general intelligence + Tiny Miracles' specific KB + Priti/Dinesh as the human verification layer.** Not just a KB lookup. The KB is authoritative when it has the answer; for everything else, Sonnet's general knowledge fills the gap, and the impact-team contacts are the safety net.

**Concretely, what this means for prompt edits:**

- **Don't artificially restrict bhAI to just the KB.** If the KB doesn't cover something (specific govt office address, a college's fee structure, a market price, a local shop), Sonnet should answer directly from its training — with appropriate hedging (*"मेरे ख्याल से"*, *"typically"*, *"around"*) — instead of deflecting to *"Google पर देखो"* or *"मेरे पास नहीं है"*. Saying "Google पर देखो" defeats the whole point: the user came to bhAI to save the trip to Google.
- **Pair Sonnet's general-knowledge answers with a verification path.** Hedged answer + Priti's number (BC docs) or Dinesh's escalation channel (MIDC docs) so the user can confirm before acting. For grievance/health/financial-crisis content, the verification path is Rishi+Anu via `ESCALATE: true`. The user gets the answer fast AND has a way to verify it — both halves matter.
- **Offer to email Priti/Dinesh on the user's behalf when the topic is govt-scheme-adjacent and the answer is consequential.** Even when bhAI has a confident general-knowledge answer, for things the user will act on (going to a specific office, applying for a scheme), proactively offer the email channel: *"मैं Priti को email कर दूँ aapki taraf से? वो confirm कर देंगी जाने से पहले।"* That's the verification AND it reduces friction (the user doesn't have to think about who to call).
- **Don't fabricate specifics under helpfulness pressure.** General-knowledge answer is fine. Inventing a specific address (*"Western Railway station-கிட்ட"*) or specific hours (*"10 AM to 6 PM"*) when those weren't actually in Sonnet's knowledge is fabrication. Hedge or omit the specific; keep the general answer + verification path.
- **Test capability expansions for accuracy.** When relaxing a "stick to KB" rule to let Sonnet answer from general knowledge, plan a small accuracy audit (replay 10-20 likely user questions through the dev bot, spot-check via web search). Sonnet is usually right on Mumbai-area common knowledge but can be confidently wrong on specifics — Priti/Dinesh verification catches this in production but eval-style spot-checks catch it pre-deploy.

**The framing for the user**: bhAI saves the user a trip to Google AND a phone call to figure out who knows. Both halves are the product. Restricting to KB-only loses the first half; removing the verification layer loses the second.

# What lives where

| Topic | File |
|---|---|
| bhAI's persona, voice, anti-sycophancy rules | [src/bhai/llm/prompts/prompt_v1_pilot.md](src/bhai/llm/prompts/prompt_v1_pilot.md) |
| End-to-end pipeline & architecture | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Past task prompts (style reference) | `tmp/*.md` |
| Contributing workflow | [CONTRIBUTING.md](CONTRIBUTING.md) |
| CI definition | [.github/workflows/ci.yml](.github/workflows/ci.yml) |
| Custom Claude Code skills | [.claude/commands/](.claude/commands/) |
| Permission allowlist | [.claude/settings.local.json](.claude/settings.local.json) |

# How to update this file

This file is supposed to capture *the things you would otherwise get wrong twice*.

- If I correct you on the same thing twice in one session, ask whether to add it here.
- If you discover a non-obvious gotcha while working, propose an addition before you forget.
- Keep it under 200 lines — when adding, look for something to delete. Length erodes adherence.
- Project-context (what bhAI does) goes in `ARCHITECTURE.md` or the prompt files. This file is for *how we work together*.
