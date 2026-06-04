# prompt_v1_pilot.md — Changelog

Reverse-chronological log of prompt edits, the production incident that triggered each, and the kind of fix applied. Each row is a sibling to a git commit but explains the **why** in a way `git log` doesn't.

When adding a row, include:
- **Date** (ISO 8601)
- **Commit SHA** (or `WIP` if pre-commit)
- **Headline** (one line — what changed in user-visible terms)
- **Trigger** (production transcript, audit document, or user feedback that prompted the edit — link if possible)
- **Fix shape** (negative ban / positive principle / structural / regex-backed / etc.) — useful for spotting patterns where we keep adding the same shape of fix

---

## 2026-06-04 — Slim-down: stop duplicating content the use-case blocks already own

**Commit**: WIP (this branch — `dev`)
**Trigger**: prompt had bloated back to **383 lines** despite the new per-turn architecture (always-loaded persona + router-selected `use_cases/<tag>.md` blocks + helpdesk KB files). Audit showed ~135 lines were straight-up duplicates of content already covered better by the use-case blocks (`general.md`, `scheme_kb.md`, `finance_advice.md`, `finance.md`, `grievance.md`). User flagged: *"our prompt has become way too big again."*
**Fix shape**: structural — move duplicated content out of the always-loaded base prompt. No behaviour change: every removed section's content already lives in the use-case block that fires when that surface is active.

Changes (383 → 271 lines, −112 lines / −29%):

- **Anti-Sycophancy section (41 lines) deleted from base.** The 6-step math procedure + example + DO NOT list is fully covered by `use_cases/finance_advice.md` (Checks 1-4 + rules of engagement). Replaced with a 3-line pointer plus the two non-financial honesty bullets (opinion-asked / upset-or-frustrated) that don't have a dedicated use-case block. The *"Sycophantic"* line in "You Are NOT" above is the always-loaded version of the principle.
- **Honesty-About-Outreach section compressed (70 → 30 lines).** Kept: section header (contract test), the `ESCALATE: true` mechanism, `ESCALATE_CATEGORY` routing table, the four hard rules (no fake attribution / no past-tense / no future-tense without ESCALATE / "did you ask Vijay" → say no), and the `web_search` tool guidance (the tool is globally available on every Claude call). Removed: the "General questions outside the KB" sub-section (fully covered by `general.md`), the restaurant example (also in `general.md`), the "Scope of named contacts" sub-section (covered by `scheme_kb.md` rule 2 + rule 7), the "Why this matters" Sapna-karate coda (covered by `general.md`'s closing paragraph).
- **"What You Can Talk About" compressed (16 → 5 lines).** The 11-language bullet duplicated the "Match the User's Language" section above; the govt-schemes + document-help bullets duplicated `scheme_kb.md`. Kept: the companionship-vs-practical-help framing and the medical/legal "always defer to professionals" carve-out (no use-case block owns those).
- **KB-as-Single-Source-of-Truth section compressed (27 → 8 lines).** Rules 1, 2, 4, 5, 6 (never invent facts, completeness on first reply, helpdesk-mode focus, know what's in your KB) are all in `scheme_kb.md`. Renamed the surviving section to **"Phone numbers in replies (pipeline contract)"** — the one rule that genuinely IS plumbing-level guidance applying to every turn that shares a number (Priti's number in `docs` surface, web_search-returned numbers in `general` surface, etc.).
- **"Mode-switching: helpdesk vs casual" subsection deleted (14 lines).** `scheme_kb.md` enforces helpdesk completeness when the docs/schemes router tag fires; the split is now architectural rather than a prompt instruction.
- **"The Intermediary Role" section deleted (7 lines).** Pure duplicate of "How outreach actually works" higher up — same content, different framing.

Surviving structure: persona / output language / personality / pop culture → Honesty-About-Outreach (compressed) → audience description + gender detection → Match the User's Language → Never narrate reasoning → What You Can Talk About (compressed) → Phone numbers pipeline → Response Length → Conversation Flow → Practical Context → Privacy → What You Are Not → Pilot Mode: Gentle Learning → TTS Output Rules.

Contract tests untouched — all required phrases verified present in the slim version (*"Honesty-About-Outreach Rule"*, *"No past-tense outreach claims"*, *"No future-tense outreach claims"*, *"मैंने पूछ लिया"*, *"ESCALATE: true"*, *"team को email करूँ"*, *"No fake attribution"*, *"document work"*, both Vijay and Priti).

No code changes. Pure prompt slim-down.

---

## 2026-05-25 — Strengthen general-knowledge mode: stop the "Google पर देखो" punt

**Commit**: WIP (this branch — `dev`)
**Trigger**: dev-bot transcript at 2026-05-25 09:28:28 IST. User asked *"कोई बढ़िया चाइनीज़ ऑप्शन दो"* (after a multi-turn budget restaurant conversation around Bombay Central). Bot replied: *"सुंदर, honestly बोलूँ — Bombay Central के पास specific Chinese restaurants के नाम और current prices मेरे पास नहीं हैं। Zomato या Google Maps पर 'Chinese near Bombay Central' search करो..."* Punting to Google instead of naming chains/areas Sonnet definitely knows is false modesty — and the user flagged it as a failure mode (normal Sonnet would name a few restaurants, hedge prices, ask follow-up).
**Fix shape**: prompt-only edit. Strengthen the "General questions outside the KB" section + scope the Sapna-karate failure narrative narrowly.

Changes:
- **"General questions outside the KB" section** rewritten and expanded. New section heading: *"answer them like normal Sonnet"*. Explicit instruction: "respond exactly the way Sonnet/ChatGPT would respond to any user asking this question on a normal day — share specific suggestions, name places and chains you actually know about." Explicit prohibition: "Do NOT default to 'Google Maps पर देखो' as the answer." Worked example (restaurant recommendation in BC area, ₹700 budget) showing the right pattern: named chains + hedged prices + follow-up question about preferences.
- **"Why this matters" coda** (Sapna karate failure narrative) narrowed: previous wording lumped "inventing specifics (specific academy, exact fees, exact schedule)" with the actual failure (fake attribution to Vijay + past-tense outreach). The breadth was mistraining the model into refusing all specifics. Now scoped to *"fake outreach attribution + past-tense outreach claims — putting words in a real person's mouth"*, explicitly distinguishing from general-knowledge suggestions.

No code changes. No regex updates needed — this is a model-behaviour calibration via prompt only.

239 tests pass.

---

## 2026-05-24 — Fix "ru p e e s" letter-by-letter TTS leak

**Commit**: WIP (this branch — `dev`)
**Trigger**: dev-bot transcript `871473eb2147` showed responses with `₹700-800`, `₹150-180 per person`, etc. Sarvam's `bulbul:v3` Hindi TTS has no pronunciation for the `₹` glyph or the English word "rupees" — it falls back to spelling them out letter-by-letter ("r u p e e s"). User caught it audibly.
**Fix shape**: pre-TTS regex normalization (in `sarvam_tts.py`, not in the prompt response cleaner — keeps the stored transcript clean with `₹` for log readability) + prompt-side instruction as defense-in-depth.

Changes:
- New `normalize_currency_for_sarvam()` in [src/bhai/tts/sarvam_tts.py](../../tts/sarvam_tts.py): converts `₹500` → `500 रुपए`, `₹500-800` → `500 से 800 रुपए`, `Rs.500` → `रुपए 500`, "rupees"/"rupee" → `रुपए`. Called inline in `_synthesize_once` right before the API payload is built.
- Prompt TTS Output Rules: new bullet — "Currency — always Devanagari, never the ₹ glyph. Write `500 रुपए` or `500-800 रुपए` — NOT `₹500`." Notes that the normalization pass exists as a safety net, but the model should produce the right form in the first place.
- 13 new unit tests in `src/tests/test_sarvam_tts.py` covering: single amounts, ranges (hyphen and en-dash), comma-grouped amounts, `Rs.` prefix, the standalone glyph, the English word in various cases, idempotence on already-Devanagari text, and a guard that `Rs` followed by a non-digit (`Rs corp`) doesn't accidentally substitute.

Only affects Sarvam TTS — ElevenLabs handles currency natively, so its path is untouched.

---

## 2026-05-22 — Honesty-About-Outreach update: bhAI CAN email now

**Commit**: WIP (this branch — `dev`)
**Trigger**: user has shipped the consent-gated `ESCALATE: true` → real Gmail email path end-to-end. The earlier Phase 1 prompt had a "this capability is being built" framing that's no longer accurate.
**Fix shape**: positive capability statement + tighter consent rule. No code changes — the regex backstop (`_detect_outreach_claim`) already handles the ESCALATE-aware case correctly.

Changes:
- Opening paragraph of Honesty-About-Outreach section rewritten from "you cannot ask anyone" to "you CAN email named contacts via consent-gated `ESCALATE: true`."
- "The one exception" sub-section renamed to "How outreach actually works" — now describes the channel as the standard mechanism, not as an exception.
- Three-step procedure made explicit: ask consent → on yes emit `ESCALATE: true` + future tense → on no drop it.
- Past-tense ban tightened: even when `ESCALATE: true` is emitted, past-tense outreach is still a lie because the email goes async after the turn ends.
- Verbal habit (line 36): "मैं Vijay से पूछ के बताऊँगी" is now allowed when paired with `ESCALATE: true` and user consent.
- "If asked 'did you ask Vijay?'" honest response updated to offer the email path rather than "directly call them."

Contract test updated to lock in the new invariants (the "team को email करूँ" consent question is now required to appear).

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
