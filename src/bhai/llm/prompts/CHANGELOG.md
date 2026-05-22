# prompt_v1_pilot.md — Changelog

Reverse-chronological log of prompt edits, the production incident that triggered each, and the kind of fix applied. Each row is a sibling to a git commit but explains the **why** in a way `git log` doesn't.

When adding a row, include:
- **Date** (ISO 8601)
- **Commit SHA** (or `WIP` if pre-commit)
- **Headline** (one line — what changed in user-visible terms)
- **Trigger** (production transcript, audit document, or user feedback that prompted the edit — link if possible)
- **Fix shape** (negative ban / positive principle / structural / regex-backed / etc.) — useful for spotting patterns where we keep adding the same shape of fix

---

## 2026-05-22 — Phase 1 anti-lying rewrites

**Commit**: WIP (this branch — `dev`)
**Trigger**: Sapna karate fabrication arc May 7–11 (`tmp/lying_audit_transcripts.md`); structural critique (`tmp/lying_audit_prompt_critique.md`); research scan (`tmp/lying_audit_synthesis.md`).
**Fix shape**: convert negative bans → positive principles + structural regex backstop in `base.py`.

Changes:
- **A1** Replaced the literal banned-phrase list ("एकदम solid plan है" etc.) with a positive shape-based rule: math first, lean second. Research basis: Semantic Gravity Wells / Anthropic's "tell Claude what to do" guidance.
- **A2** Carved out deferrals from the "always end with a hook" rule — a clean "मुझे नहीं पता" is a complete response and must not be appended to with speculation.
- **A3** Removed "Don't round" from the anti-sycophancy math procedure (potentially confusing for TTS-friendly Devanagari numbers).
- **A4** + **A8** Rewrote the "Honesty About Outreach" section: bhAI cannot message anyone today; the only legitimate outreach channel is consent-gated `ESCALATE: true`; named contacts (Vijay, Priti, Rishi, Sarfaraz, Vidhi, impact team) get a direct-call routing instead of "I'll ask them for you" framing. Verbal habit at line 32 ("मैं पूछ के बताती हूँ as positioning") replaced with KB-check phrasing.
- **A5** Compressed the 12-line "Never narrate your reasoning" section to 2 lines (regex backstop in `base.py:_strip_reasoning_leak` does the actual work).
- **A6** Removed the markdown ban from the prompt (regex backstop in `base.py:_strip_markdown` is the actual enforcement).
- **A7** Minor compression on the KB-coverage list.
- **B1** New regex backstop `_detect_outreach_claim` in `base.py` — flags past-tense and (non-ESCALATE) future-tense outreach claims against named contacts; triggers a one-shot LLM re-prompt with a corrective system message.
- **B2** Extended `memory/summarizer.py` fact extraction to capture user gender when grammatically signalled; the prompt's gender-detection section now reads extracted facts first.

Net line delta: ~−10 lines. Real change: competing-rule density drops; structural enforcement replaces aspirational bans.

---

## 2026-05-12 — Escalation flag wired to real email

**Commit**: `a664eb9` — `feat(escalation): wire ESCALATE flag to real impact-team email`
**Followed by**: `8e8a2a8` — `fix(escalation): switch email transport from Gmail SMTP to Gmail API`
**Trigger**: ESCALATE: true was previously emitted but no email went anywhere (per `ARCHITECTURE.md §8`, this was "future work"). This commit closed that gap.
**Fix shape**: structural (capability now matches the prompt's promise; "Main team ko email kar rahi hoon" is now actually true when the flag is set).

---

## 2026-05-08 — Strip chain-of-thought leakage

**Commit**: `75f9a1c` — `fix: strip chain-of-thought leakage from LLM responses`
**Trigger**: Manimala Malayalam reasoning leak (May 11 incident — the bot literally narrated its own system-prompt rule conflict to the user; see `tmp/lying_audit_transcripts.md` Incident 2).
**Fix shape**: regex backstop. Added `_strip_reasoning_leak` in `base.py`; prompt section asking the model not to narrate is now load-bearing-less.

---

## 2026-05-06 — Refine intro phrasing + anti-sycophancy framing

**Commit**: `a507b06` — `feat(prompt): refine intro phrasing and anti-sycophancy framing`
**Trigger**: Critique pass over the v1_pilot prompt (`tmp/prompt_v1_pilot_critique.md`).
**Fix shape**: positive principles + scoping. Intro line shortened; anti-sycophancy reframed to "math first" shape (still with a literal-string ban, replaced in 2026-05-18 above).

---

## 2026-05-05 — Loosen no-confab rule

**Commit**: `bb7e91f` — `feat(prompt): loosen no-confab rule — answer general questions, ban only fabrication`
**Trigger**: Over-correction from the prior commit (`4f78129`) was making bhAI refuse legitimate general questions (kids' classes, local prices).
**Fix shape**: scoping. Added the "general questions outside the KB — answer them" carve-out so Sonnet's normal hedged general-knowledge response is the default for non-KB topics.

---

## 2026-05-03 — Trust-repair endpoint + hard ban on confabulated outreach

**Commit**: `4f78129` — `feat: trust-repair endpoint + hard ban on confabulated outreach claims`
**Trigger**: First documented incident of bhAI claiming past-tense outreach actions it hadn't performed (precursor to the Sapna karate arc later in May).
**Fix shape**: negative ban (which we now know is structurally weak — superseded by 2026-05-18 above).

---

## Older entries

Prior commits (`ef68c74`, `6435a6a`, `39808f2`, …) are pre-changelog. Backfill from `git log -- src/bhai/llm/prompts/prompt_v1_pilot.md` as needed.
