# bhAI v2 Proactive — the build arc (loop → safety → utility)

Companion to [v2_proactive_design.md](v2_proactive_design.md) (the architecture, signed off 2026-06-01) and [v2_agent_tuning_prompt.md](v2_agent_tuning_prompt.md) (the 2026-06-08 replay findings). This doc is the **roadmap**: it reframes the 5 replay findings into 3 phases, scopes each, and lists the decisions that are Sundar's to make before code. Nothing here is built yet — this is for sign-off.

Branch: `v2/proactive`. Test surface: [scripts/v2_thread_replay.py](../scripts/v2_thread_replay.py) + a contract test per incident class in [src/tests/test_contracts.py](../src/tests/test_contracts.py).

---

## The one-paragraph thesis

The proactive framework's **bones are good** — the brainstorm→critique→tools→draft→judge chain ([thinker.py](../src/bhai/proactive/thinker.py)) with per-stage temperatures, the threads persistence layer ([threads.py](../src/bhai/proactive/threads.py)), the working PII/content scrub layer, and the fallback discipline are all sound. The problem is the **loops are open**. The agent acts, but it does not durably remember *that* it acted, *how the user reacted*, or *what state the relationship is in*. v2's entire selling point — "works for the user across days without being relentless" — requires those loops closed. The 5 replay findings are mostly symptoms of this.

---

## The 5 findings collapse into 3 root causes

| Replay finding (2026-06-08) | Root cause | Phase |
|---|---|---|
| #4 joke fan/AC repeated 5× across afternoons | **Open feedback loop** | 1 |
| #5 `silent_day_reason` never fires / weak anti-relentless gate | **Open feedback loop** | 1 |
| #1 thinker re-picks `active` `saree_business_expansion` (2× confirmed, not 3) | Open loop + soft thread filter | 1 → 2 |
| #2 Sapna got 0 threads across kid-classes + lying confrontation | **Reactive thread extraction under-fires** | 2 |
| #3 post-confrontation tone-deafness | **No durable trust-state** | 2 |
| (the bigger ask) artifacts/utility underused; can't act for the user | **Capability gap** | 3 |

### The structural fact under findings #1/#4/#5

Every prompt that prevents relentlessness reads `nudge_history.md`:
- [brainstorm_v1.md:31](../src/bhai/proactive/prompts/brainstorm_v1.md#L31) — "Read `nudge_history.md` FIRST."
- [critique_v1.md:18](../src/bhai/proactive/prompts/critique_v1.md#L18) — "Scan `nudge_history.md` for the last 14 days."
- [joke_v1.md:16](../src/bhai/proactive/prompts/joke_v1.md#L16) — "Don't pick a vault joke sent in the last 30 days."

That file is a **hardcoded placeholder** ([dossier_loader.py:418-420](../src/bhai/proactive/dossier_loader.py#L418-L420) → `"_no proactive nudges delivered yet_"`). The underlying `nudges` table stores only `(phone, slot, last_sent)` — a bare throttle timestamp ([store.py:71-76](../src/bhai/memory/store.py#L71-L76)). So the agent has **no durable memory of anything it has ever said.** `outreach_history.md` is likewise a placeholder ([dossier_loader.py:415-417](../src/bhai/proactive/dossier_loader.py#L415-L417)).

This is an **implementation gap, not a design decision** — the architecture doc §8 already specified the exact `nudge_history.md` format including user reactions ([v2_proactive_design.md:531-548](v2_proactive_design.md#L531)). We never built it.

> ⚠️ Doc correction (trust-code-over-docs): the tuning prompt's finding #4 says *"`nudge_history` table exists; wire it."* It does **not** exist. Only the throttle `nudges` table exists. Phase 1 creates the storage.

---

## Phase 1 — Close the feedback loop (the foundation)

**Why first:** until the agent durably knows what it said and how the user reacted, every downstream feature is relentless, repetitive, or blind. Kills #4 and #5 outright; removes the open-loop half of #1.

### What changes

1. **New `nudge_log` table** (keep `nudges` as the throttle gate — don't overload its `(phone, slot)` PK). Columns mirror design §8: `id, phone, slot, category, thread_slug, joke_tag, text_enc, delivered_at, reaction_enc, reaction_status, reacted_at`. Text + reaction Fernet-encrypted (PII rule). New store methods: `log_nudge_delivered(...)`, `record_nudge_reaction(...)`, `recent_nudges(phone, days)`, `recent_joke_tags(phone, days)`.
2. **Render `nudge_history.md` from real rows** ([dossier_loader.py](../src/bhai/proactive/dossier_loader.py)) — replace the placeholder, group by date, show category/topic/text/reaction/status exactly as design §8 specifies. Same for `outreach_history.md` in Phase 3.
3. **Wire delivery → log.** `record_nudge_outcome` ([store.py:656](../src/bhai/memory/store.py#L656)) currently only bumps the throttle + thread state; extend it (or the delivery hook) to append a `nudge_log` row. The replay harness already holds the full `cand` at the call site ([v2_thread_replay.py:431](../scripts/v2_thread_replay.py#L431)), so it can pass text/category/joke_tag.
4. **Capture the reaction (the closing half).** On the reactive side ([telegram_webhook.py](../inference/webhooks/telegram_webhook.py)), when an inbound message arrives within a window (e.g. 24h) of an un-reacted nudge, link it: store the reaction text + coarse `reaction_status`. For pilot, store raw + coarse status (`replied` / `no_reply_24h` via a sweep) — let the brainstorm prompt interpret nuance. See open question Q1.
5. **Belt-and-suspenders joke dedup.** With `joke_tag` logged, add a *hard code-level* exclude in `think_joke` ([thinker.py:406](../src/bhai/proactive/thinker.py#L406)) via `recent_joke_tags(phone, 30)`, in addition to the prompt now having real history. Joke repeats are the most visible failure; don't rely on the prompt alone.

### Files
`store.py` (table + methods), `dossier_loader.py` (render), `thinker.py` (joke dedup + carry `joke_tag` on `NudgeCandidate`), joke vault files (confirm each joke has a stable `*tags:` line — the `_fallback_joke` parser already expects it), `telegram_webhook.py` (reaction capture), `v2_thread_replay.py` (pass full metadata; the chronology's later user turns *are* the reactions).

### Acceptance
- Replay dossier's `nudge_history.md` shows real prior nudges with reactions.
- Fan/AC joke appears ≤1× per user per 30-day window; re-run shows zero exact joke repeats.
- New contract test in `test_contracts.py`: deliver 3 nudges → history renders all 3; `recent_joke_tags` excludes a just-used tag; a reply within 24h attaches to the right nudge.

---

## Phase 2 — Relationship safety (#2, #3, rest of #1)

**Why second:** highest user-harm risk, and the trust-state mechanism is structural (not a one-off prompt tweak). Builds on Phase 1's reaction data.

### What changes

1. **Broaden reactive thread extraction.** `THREAD_INSTRUCTION` ([base.py:91-149](../src/bhai/llm/base.py#L91)) has exactly one worked example, finance-shaped (the saree loan). Add 2–3 non-finance worked examples — a child's classes/education plan, a workplace-fairness concern, an emotional state worth gently revisiting — and explicitly lower the bar for those. This is the direct fix for Sapna's 0 threads.
2. **Durable trust-state (the real fix for #3).** The replay's May 11 trust-repair nudge was *luck* — the confrontation was still in the 20-turn recent window ([build_agent_input recent_turns=20](../src/bhai/proactive/agent_input.py#L90)). Once it ages out, the bot blunders back in. Fix: a small `relationship_state` table (`phone, trust_status, cooldown_until, reason`), surfaced in the dossier. On a trust rupture, the reactive LLM sets a cool-down; during cool-down the thinker suppresses the joke slot and routes substantive slots to a warmth-only trust-repair template. Detection: reactive-LLM-emitted (it already sees the turn) — see Q3.
3. **Hard dormant filter for grounding.** Brainstorm only "prioritises dormant" ([brainstorm_v1.md:33](../src/bhai/proactive/prompts/brainstorm_v1.md#L33)) — make it *exclude* active for grounding, with the critique's existing "user re-raised = responsiveness" exception ([critique_v1.md:26](../src/bhai/proactive/prompts/critique_v1.md#L26)) now backed by Phase 1's reaction data (we can actually tell if she re-engaged).

### Files
`base.py` (THREAD_INSTRUCTION examples + trust-rupture directive), `store.py` (relationship_state table + methods), `dossier_loader.py` (surface trust-state), `brainstorm_v1.md` / `critique_v1.md` (cool-down honoring + hard dormant filter), `thinker.py` (cool-down routing), contract test.

### Acceptance
- Replay: Sapna gets ≥1 thread (e.g. `kid_classes`); the trust rupture sets a cool-down; the next morning slot is a trust-repair check-in **even with the confrontation forced out of the recent window**; no joke fires during cool-down.

---

## Phase 3 — Genuine utility (the "be useful" ask)

**Why third:** it's the payoff, but only trustworthy once 1 & 2 stop it from being relentless or tone-deaf. Good news: the tools are **already fully functional** — `web_search` (Google CSE), `nanobanana` (Gemini image gen), `kb_read`, `tts_draft` all make real calls behind the working scrub layer. They're just **underused and crudely briefed.**

### What changes

1. **Real tool-brief composition.** `_compose_tool_brief` ([thinker.py:693-717](../src/bhai/proactive/thinker.py#L693)) just returns `chosen.summary`/`chosen.trace` verbatim — too crude to make web_search/nanobanana actually useful. Add an LLM-composed, scrubbed brief step (the design called this a "v1.5 knob"). The scrub layer stays exactly as-is — it's solid (blocks names, BC/MIDC, communities, staff, religion/caste/disability/medical/financial before any egress).
2. **Make artifacts actually fire.** The `artifact` category is "strongly preferred" ([brainstorm_v1.md:40](../src/bhai/proactive/prompts/brainstorm_v1.md#L40)) but the replay was mostly check-ins + jokes. Tune brainstorm/critique to surface tool-backed candidates; the draft already knows how to voice them ([draft_v1.md:74-93](../src/bhai/proactive/prompts/draft_v1.md#L74)).
3. **Wire the verification/outreach path** (CLAUDE.md design philosophy: "offer to email Priti/Dinesh on the user's behalf"). The proactive side currently has **zero** wiring to the escalation handler (confirmed: no imports of `handle_escalation` in `src/bhai/proactive/`). Per design §10, the proactive agent does **not** send email directly — for a govt-scheme-adjacent, consequential nudge it *offers in voice* (*"मैं Priti को email कर दूँ aapki taraf से?"*); on the user's next-turn consent, the existing reactive escalation flow ([handler.py:139](../src/bhai/escalations/handler.py#L139), routing BC→Priti / MIDC→Dinesh / unknown→both) fires. Phase 3 adds: brainstorm/draft can propose the offer, and offers/sends get recorded to `outreach_history.md`.

### Files
`thinker.py` (brief composition), `brainstorm_v1.md` / `critique_v1.md` / `draft_v1.md` (lean into artifacts + email-offer), `dossier_loader.py` (render `outreach_history.md`), `store.py` (outreach log or reuse escalation records).

### Acceptance
- Dry-run: some slots produce real artifacts (a saree logo PNG; a web-search-backed scheme answer with hedge + verification path). Manimala's saree thread proposes a logo **once** (gated by Phase 1, not 3× relentlessly).
- A scheme-adjacent candidate offers the Priti email; `outreach_history.md` records it.
- **Accuracy spot-check before any deploy** (CLAUDE.md): replay 10–20 likely questions, web-verify specifics; email Anu (cc Sundar) on any KB staleness found.

---

## Cross-cutting

- **Test every phase on the replay harness** + add a contract test per incident class (`test_contracts.py` is the regression suite for past pilot failures).
- The current chronologies ([v2_thread_replay.py:70-132](../scripts/v2_thread_replay.py#L70)) may need extending to exercise reactions (Phase 1), cool-down (Phase 2), and utility (Phase 3) — possibly a 3rd synthetic user.
- **Don't touch the reactive `_call_api` path** (tuning prompt ship rule) and don't merge to `main`. Pre-commit hooks (black/isort/mypy/pytest) stay on.
- Sequencing is strict: **1 → 2 → 3.** Phase 2's "did she re-engage?" and Phase 3's "did the artifact land?" both depend on Phase 1's reaction loop.

---

## Decisions for Sundar (before code)

1. **Q1 — Reaction classification.** Coarse status (`replied` / `no_reply_24h`) + raw text, let brainstorm interpret? *(My lean: yes, for pilot. A cheap LLM classifier is a Phase-1.5 knob.)*
2. **Q2 — Cool-down vs. "never silent-day".** Your 2026-06-02 rule is never-silent. During a trust cool-down, do we send a warm *minimal* check-in (honors never-silent, just gentle) or actually go quiet? *(My lean: warm-minimal.)*
3. **Q3 — Trust-rupture detection.** Reactive-LLM-emitted tag (it already sees the turn) vs. a thinker-side classifier? *(My lean: reactive-emitted.)*
4. **Q4 — Storage shape.** New `nudge_log` table (keep `nudges` as throttle) — confirm vs. any preference to fold it in.
5. **Q5 — Phase 3 outreach model.** Confirm the design-§10 model (offer-in-voice + consent-via-reactive, no direct proactive send) still holds, or do you want the proactive agent to draft escalation emails directly?

---

## Addendum — 2026-06-09 live replay (post Phase-1) eval + fixes

Phase 1 verified live (`tmp/v2_thread_replay_2026-06-09_2112/`): joke dedup works (0 per-user repeats vs 2×/3× before), 8 reactions attached, `nudge_history.md` populated. The run also surfaced these, which reshape Phase 2/3:

| # | Event (cite) | Diagnosis | Fix | Status |
|---|---|---|---|---|
| A | bhAI apologised to Sapna in **masculine** self-forms ("नहीं कर सकता / बोलूँगा") on the proactive morning-after nudge | proactive `draft_v1.md` lacked the "always female" rule the reactive prompt has ([prompt_v1_pilot.md:27](../src/bhai/llm/prompts/prompt_v1_pilot.md#L27)) | added feminine-self-reference rule to `draft_v1.md` + a `respectful_speech` fail in `judge_v1.md` | ✅ done (prompt-only; re-verify next replay) |
| B | reactive bot **fabricated** local specifics — "painting options around Sir J.J. School of Art ₹500–1500", "SAI centres Andheri ₹200–400" — Sir J.J. is a BFA/MFA degree college, no kids' classes | reactive path has **no tools**, so it can only fabricate-or-defer; it fabricated-asserted | **wire `web_search` into the reactive path** (NOT email Priti — that's for consequential docs/schemes only). Stopgap: harden anti-fabrication → honest defer | ⏳ Phase 3 |
| C | margin nudge invented a goal — *"पहली deal में घाटा नहीं चाहिए, पर बहुत कम profit भी नहीं"* — Manimala never stated it | helpfulness-completion reflex: model supplies the *interpretation*, deciding what she should want | brainstorm/draft principle: **present analysis, ask for the goal, don't assume it** (inform, don't decide) | ⏳ Phase 2 |
| D | Manimala said "new customer via **WhatsApp group**"; bot tunnel-visioned to margin, never asked what the group is | **brainstorm is finance/risk-skewed** — reaches for cost/margin/grievance lenses, misses growth/marketing/opportunity. Same shape as the Sapna karate→ambitions subtext miss | de-skew the brainstorm (see prompt principle below) + **artifact pipeline**: read the WA group as a distribution channel → offer a nanobanana **catalog/pamphlet** of her sarees | ⏳ Phase 2 (lens) + Phase 3 (artifact) |
| E | thinker re-grounded in `active` threads with no new info → 4× filler greetings tagged as thread-grounded | `brainstorm_v1.md:33` "prioritise dormant" is a soft hint; "never silent-day" forces filler | hard-gate active re-picks **using reaction data** (don't re-pitch what she didn't answer); revisit never-silent | ⏳ Phase 2 |
| F | `daughter_recovery` correctly went `do_not_nudge` and was never poked | sensitivity is pure LLM discretion (no deterministic trigger); bar under-specified (only "medical/loss" examples) | broaden sensitivity examples (caste/disability/abuse/shame); auto-`mark_sensitive` on trust-rupture | ⏳ Phase 2 |

### Prompt-design principle (de-skew without piling examples)

The finance skew is **not** "too few marketing examples" — it's the prompt *enumerating domains* (`scan financial_threads / grievance_log / scheme_status`) and the dossier bucketing into those same domains. Enumerating coverage narrows it. Claude 4.x follows clear instructions and **does not silently generalise from one example to another**, so a finance-heavy example set biases toward finance.

Rule of thumb for this codebase:
- **Instructions (abstract, minimal) carry COVERAGE + GOALS** — replace domain enumeration with the objective: *"find what would genuinely move this person forward today — an opportunity to seize, a risk to manage, a skill to build, a worry to ease."* This unlocks Sonnet's generality.
- **Examples carry CALIBRATION of fuzzy judgment** — the creepy/care line, respectful register, don't-fabricate, don't-assume-her-goal. Use 2–5 *contrastive* (good vs bad) examples drawn from **real pilot failures** (the boundary cases), not the obvious ones. Positive > negative examples.
- **Never use examples to enumerate domains/coverage** — that's the overfitting trap.
- **You can't reason your way to the right prompt — A/B it on the replay harness.** The replay IS the eval; change → run → check coverage broadened without breaking the relentless/creepy guards.

### Refined phase scopes (sense → judgment → hands)

- **Phase 1 — SENSES (done):** the agent perceives what it said + how she reacted (`nudge_log` + reactions + real `nudge_history.md`).
- **Phase 2 — JUDGMENT (prompt + light state, no new powers):** stop relentless active re-picks using reaction data (E); reliable cross-domain thread extraction (#2); durable trust-state + broader sensitivity (F, #3); de-skew brainstorm to opportunity+risk+skill+worry (D-lens); don't-assume-the-goal (C); revisit never-silent-day (E).
- **Phase 3 — HANDS (the agentic tool-use loop + real powers):** `web_search` in the reactive path (B); iterative tool-brief composition (search→read→refine); artifact generation that lands — nanobanana **catalogs/pamphlets** (D), rendered debt/margin sheets; the opportunity→artifact pipeline.

Ordering rationale: **hands without judgment is dangerous** (a relentless catalog-spammer is worse than no catalog), and **judgment without senses is blind**. So senses → judgment → hands.
