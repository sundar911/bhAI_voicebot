# Items deferred to v2 (the true v2 driven by Sid's new direction)

Surfaced during v1.5 dev-bot testing but explicitly scoped out for now.
Don't lose these; revisit when v2 planning starts.

## 1. "interest" / "byaaj" — model ignores the Hindi-preference rule

**Observed**: 2026-05-26 dev test — Sundar spoke Hindi throughout, bot still
used English "interest" in finance_advice replies despite the
finance_advice.md vocabulary principle ("prefer Hindi/Marathi for
specialised finance terms").

**Why it's deferred**: Sundar's call (2026-05-26 evening) — *"I think it can
be understood in context a little. Let's fix this later."* The word
*"interest"* is intelligible to most Hindi-speaking users in financial
context, so this is a polish issue, not a correctness issue. The
prompt-level fix has been attempted (finance_advice.md vocabulary
principle); the model still drifts.

**Possible fix paths for v2**:
- **(a) Stronger prompt instruction** — add explicit wrong→right examples
  inline in finance_advice.md ("❌ *'interest कितना है?'* ✅ *'ब्याज कितनी है?'*"). Risk: rules don't always hold once persona pressure stacks up.
- **(b) Runtime regex replacement** — post-process Hindi/Marathi-mode
  responses to substitute *"interest"* → *"ब्याज"*, *"tenure"* → *"कितने महीने"*, etc. Cheap and reliable, but brittle for natural-language exceptions
  ("interest" in the sense of "she has interest in coding" — unrelated).
- **(c) Wait for Sid's v2 direction** — the persona / vocabulary
  philosophy might shift entirely in v2, making this moot.

Recommend (c) for now; (b) as a fallback if v2 drags.

## 2. Bot misses "instant" / "online" alternatives when the KB lists them

**Observed**: 2026-05-26 — when asked about PAN card, bot gave the centre-visit
flow (Marol Pipeline Road, ₹93, 15-20 days) but **completely omitted the
instant e-PAN option** that's right there in the KB at
[pan_card.md:39](../knowledge_base/helpdesk/pan_card.md#L39): "Instant
e-PAN can be generated in 10 minutes via Income Tax portal if Aadhaar is
mobile-linked." This is dramatically faster + free, and skipping it sent
the user toward an unnecessary trip.

**v1.5 fix attempted**: added a rule to
[scheme_kb.md](../src/bhai/llm/prompts/use_cases/scheme_kb.md) saying *"lead
with the fastest/cheapest path when alternatives exist."* Whether the model
follows this consistently is an open question — needs evals.

**For v2**: consider building a small "options table" rendering convention
in KB files (`## Options` section with explicit speed/cost columns) so the
model can't miss the comparative info even when it's text-buried.

## 3. Bank account suggestions need better locality-awareness

**Observed**: 2026-05-26 — bot said *"किसी भी सरकारी bank में जाओ"* — too
vague to act on. Sundar wants location-aware suggestions ("ask user's area,
then suggest specific banks nearby").

**v1.5 fix shipped**:
- Updated [scheme_pmjdy.md](../knowledge_base/helpdesk/scheme_pmjdy.md) with
  a "Choosing a Bank — Practical Guidance for Mumbai Users" section
  including the ask-locality-first principle and a list of major sarkari
  banks with general Mumbai coverage.
- Updated [scheme_kb.md](../src/bhai/llm/prompts/use_cases/scheme_kb.md) to
  explicitly call out the bank-account case.

**For v2 (if needed)**: actual branch-address data per area. Would need a
verified `bank_branches.md` keyed by station/locality. Probably overkill
for a voice bot — Google Maps does this well already. Defer.

## 4. /start latency perception

**Observed**: 2026-05-26 — Sundar said the intro felt slow / he had to send
a voice note before getting a reply.

**Investigation**: server-side timestamps show intro fires same-second as
/start. Perceived delay is TTS generation + CDN upload + client-side
download/play (~3-7s normal for a long voice note over Indian mobile).

**For v2**: consider a "text-first then voice" onboarding pattern. The intro
text arrives instantly ("भाई हाज़िर — voice note में बताती हूँ अभी") followed
by the full intro voice ~5s later. Improves perceived snappiness without
changing the actual voice generation time.

## 5. PAN/Voter centre defaulting to MIDC before asking BC/MIDC

**Observed**: 2026-05-25 — bot gave Marol PAN centre as the default before
confirming the user's office. User worked at BC and would have needed the
BC-area centre.

**For v2**: either ask BC/MIDC FIRST for any document help (mirrors the
escalation precondition), OR list BOTH centres with the "which is
closer to you?" question at the end. The current behavior of defaulting
to one centre is a slight scoping flaw.

---

*Last updated: 2026-05-26 evening. Re-read this when v2 planning starts.*
