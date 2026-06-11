Evaluate whether bhAI is actually **working for each user** — across both surfaces (the reactive reply flow AND the proactive nudge flow) — and turn the findings into concrete, implementable changes. This is the central judge: one question, *is the bot earning its place in her day?*, plus the first step of a self-improving loop (**measure → recommend → a human/agent implements on dev → re-measure**).

## Data collection
1. **Dashboard** (WebFetch): `https://bhaivoicebot-production.up.railway.app/dashboard?key=bhai-pilot-2026` — per-user message counts, response times, failures, first/last active.
2. **Transcripts** for each pilot user (skip `4aabfb2a4df9` + `871473eb2147` = Sundar testing), ALL in parallel (WebFetch): `https://bhaivoicebot-production.up.railway.app/conversations/{phone_hash}?key=bhai-pilot-2026`.
3. Identify users by self-introduction (see `/pilot-report` for the live hash→name map; reconfirm from the transcript, the prod hashes drift).

## Surface 1 — the reactive reply flow
The unit is the **triple**: `[her message → bot reply → her next message]`. Her next message is the real signal — engagement, confusion, or withdrawal. For a sample of triples per user, judge:
- **Reply quality**: did it answer what she actually asked? Right length (voice-note-friendly), right warmth, her language? Did it defer cleanly when it should, or fabricate/over-promise?
- **Memory / thread sense**: did the bot remember relevant facts, and did any `<thread>` it opened/closed make sense (or was it noise / a missed durable concern)?
- **Her reaction**: did she engage warmly, answer the bot's hook, go quiet, correct it, or get frustrated? Quiet-after-a-question and corrections are the strongest negative signals.
- **Failure classes to tag**: fabrication (a fact/number/attribution it didn't have), over-promise (claimed outreach without the flag), language mismatch, tone miss (too jokey when serious / too clinical when warm), length (rambling), repetition (re-asked something).

## Surface 2 — the proactive nudge flow
A **nudge** is an assistant message in a slot window (morning ~10:00, afternoon ~14:00, night ~21:00, ≤30 min in) following a >30 min gap; its **reaction** is the first user reply within 24h (mirrors `src/bhai/proactive/monitor.py`). Judge:
- **Reaction rate** overall and **by slot** — does morning land but night get ignored?
- **What lands vs. noise** — name the *type* (a kid check-in, a follow-up on something she raised, a genuinely funny joke) vs. silence/one-word brush-offs.
- **Relentlessness** — the same topic or joke fired again after it already flopped (the bug class the feedback loop exists to kill). Flag every repeat.
- **Trust / withdrawal** — shorter replies or longer gaps after a string of nudges; any `trust_repair` situation and whether the bot slowed down.

## Per-user utility verdict
One line per user: **adds utility / neutral / net-negative**, with the single strongest piece of evidence across both surfaces. Be honest — low engagement with no warmth is net-negative even if delivery "worked".

## Recommendations — the self-improving step (most important section)
Turn the evaluation into a **ranked list of concrete, implementable changes**. Each one must be specific enough that an engineer/agent can act on it without re-deriving it. For each:
- **Observation** (the evidence: which users, what pattern, how often — no quotes/PII).
- **Change**: the exact knob — *which file or setting*, and *what* to change. Real targets:
  - `src/bhai/llm/prompts/prompt_v1_pilot.md` (cross-cutting persona/voice/honesty)
  - `src/bhai/llm/prompts/use_cases/*.md` (a specific surface)
  - `src/bhai/proactive/prompts/*.md` (nudge brainstorm/critique/draft/judge)
  - nudge cadence / slots (`config.nudge_*_hour_ist`), the AWAITING relentlessness guard, thread thresholds
- **Expected effect** + **how the next /monitor run will confirm it** (the metric that should move).
- **Confidence** (high / medium / low) and whether it needs a human call (e.g. a routing or escalation change) vs. safe to apply on dev.

Bias toward **few, high-confidence** changes over a long speculative list. If the evidence is thin (early data, one slot barely used), say so rather than invent a pattern.

## Report format
Write to `/private/tmp/bhai_monitor_report.txt`:
```
bhAI MONITOR — {date}    Window: last {N} days
════ EXECUTIVE SUMMARY ════  is the bot earning its place? biggest win, biggest leak (3-5 bullets)
════ ENGAGEMENT ════         table: User | Msgs | Reply-quality read | Nudges | Reacted | Utility verdict
════ REACTIVE: what's landing / failing ════  aggregated reply-quality patterns + failure-class counts
════ PROACTIVE: what's landing / noise ════   reaction rate by slot; relentlessness & trust flags
════ PER-USER VERDICTS ════  verdict + evidence + the one change
════ RECOMMENDATIONS (ranked) ════  the self-improving step — observation → change (file/knob) → expected effect → confidence
```

## Privacy (CRITICAL — same as /pilot-report)
NEVER include user quotes, message/nudge content, or phone numbers. Describe TYPES and PATTERNS; first names only if self-introduced; everything aggregate. Safe to share with the team.

## The loop
After recommended changes land on **dev** and run for a window, re-run `/monitor` and check the metrics named in each recommendation actually moved. That measure→recommend→implement→re-measure cycle is the self-improving system — start human-in-the-loop (an engineer/agent applies the changes), tighten as confidence in the recommendations grows.

## Arguments
- A `phone_hash` → detailed single-user report (both surfaces, still no quotes).
- `days=N` → window (default 30). `reactive` / `proactive` → restrict to one surface.
