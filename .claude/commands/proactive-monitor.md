Generate a bhAI **proactive-surface** monitoring report — does the nudge layer actually earn its place in each user's day, or is it noise they tolerate? This is the sibling of `/pilot-report` (which covers the reactive surface); here the unit of analysis is the **nudge and the user's reaction to it**.

The core question, per user: **is bhAI being of utility, or just talking at her?**

## Data collection

1. **Fetch dashboard metrics** with WebFetch:
   `https://bhaivoicebot-production.up.railway.app/dashboard?key=bhai-pilot-2026`
   Per-user message counts, response times, first/last active.

2. **Fetch conversation transcripts** for each pilot user (skip phone_hash `4aabfb2a4df9` — Sundar testing) with WebFetch, ALL users in parallel:
   `https://bhaivoicebot-production.up.railway.app/conversations/{phone_hash}?key=bhai-pilot-2026`
   These carry the nudges (assistant messages) AND the user's replies — the raw material for reaction analysis.

3. **Known users** (label by self-introduction; reuse the `/pilot-report` mapping):
   - `6340a9665a56` = User A (Manimala) · `5958881a84cf` = User B · `118275a2cd51` = User C
   - `decaa6a18773` = User D (Sapna) · `f526a9d8b180` = User E (Jyoti)
   - New phone_hashes → User F, G, … · `6704c5df5504`, `0364ccdccbaf` = non-pilot testers (flag, don't analyze for utility)

## Identifying nudges and reactions (the heuristic)

bhAI fires at most one nudge per slot per day. In the transcript, a **nudge** is an assistant message where BOTH hold (mirrors `src/bhai/proactive/monitor.py` — keep them in sync):
- Its IST timestamp lands inside a slot window: **morning ~10:00**, **afternoon ~14:00**, **night ~21:00**, within the first ~30 min of the hour.
- The previous message is **> 30 min earlier** (so it's not a reactive reply that merely fell in the window).

A nudge's **reaction** is the first **user** message after it, within **24h**, with no intervening assistant turn. No such message → **no reaction** (silence is data).

## Analysis

### Per-user nudge engagement
- Nudges delivered (total + by slot) over the window.
- **Reaction rate** = nudges that got a reply ÷ nudges delivered. Break down by slot — does morning land but night get ignored?
- Trend: is the reaction rate rising, flat, or decaying over the weeks?

### What lands vs. what's noise
- **Lands**: nudge types that reliably draw a warm reply — a check-in on a child, a follow-up on something she raised, a genuinely funny joke, a scheme update she acted on. Name the *type*, not the content.
- **Noise**: nudges that get silence or a one-word brush-off. Look for **relentlessness** — the same topic or the same joke fired again after it already flopped (this is the bug class the feedback loop exists to kill; flag any repeat offender).
- **Wrong-channel**: catalog/list-type content that should have ridden the text_artifact channel but went into a voice note (emoji-in-voice).

### Trust & tone signals
- Any sign a nudge irritated her or that she withdrew after a string of nudges (shorter replies, longer gaps, "mat bhejo")? Flag as a trust risk.
- Did a `trust_repair` situation arise (she felt misled / over-promised)? Did the bot slow down appropriately?
- Did the nudge respect sensitive topics (no unsolicited follow-up on grief, debt, health shame)?

### Utility verdict (the headline)
For each user, one line: **adds utility / neutral / net-negative**, with the single strongest piece of evidence. Be honest — a low reaction rate with no warmth is net-negative even if delivery "worked."

### One concrete change per user
The highest-leverage single change to the proactive behaviour for this user (e.g. "drop the night slot — 0/9 reactions", "stop the supplier-vetting follow-ups — she closed that chapter", "more kid check-ins — every one got a reply").

## Report format

Write to `/private/tmp/bhai_proactive_report.txt`:

```
bhAI PROACTIVE-SURFACE REPORT — {today's date}
Generated: {timestamp}   Window: last {N} days

════════════════════════════════════════
EXECUTIVE SUMMARY
════════════════════════════════════════
3-5 bullets: is the nudge layer earning its place? Biggest win, biggest leak.

════════════════════════════════════════
NUDGE ENGAGEMENT DASHBOARD
════════════════════════════════════════
Table: User | Nudges | Reacted | Rate | Morning | Afternoon | Night | Utility verdict

Portfolio: overall reaction rate, best/worst slot, # relentlessness flags.

════════════════════════════════════════
WHAT LANDS / WHAT'S NOISE
════════════════════════════════════════
Aggregated nudge TYPES that work vs. fall flat. No quotes, no content.

════════════════════════════════════════
RELENTLESSNESS & TRUST FLAGS
════════════════════════════════════════
Repeated topics/jokes after a flop; withdrawal signals; trust_repair cases.
Each flag → user label + slot + what repeated. These are action items.

════════════════════════════════════════
PER-USER VERDICTS
════════════════════════════════════════
User X — verdict + evidence + the one change.

════════════════════════════════════════
RECOMMENDATIONS
════════════════════════════════════════
Prioritized, system-level (prompt/slot/cadence changes) + per-user changes.
```

## Privacy rules (CRITICAL — identical to /pilot-report)
- NEVER include user quotes or message/nudge content. Describe TYPES and PATTERNS.
- NEVER include phone numbers — use labels (User A, B, …).
- First names only if the user self-introduced.
- Everything aggregate: "3 users ignored the night slot", not "Sapna ignored…".
- The report is safe to share with the broader team.

## Arguments
- If `$ARGUMENTS` is a phone_hash, produce a detailed single-user proactive report for that user only (still no quotes).
- If `$ARGUMENTS` contains `days=N`, scope the window to the last N days (default 30).

## Note on data freshness
The proactive layer (v2) may not be fully live in prod yet — early data is the v1.5 morning/night check-ins. If a slot has near-zero nudges, say so rather than inferring a pattern from one data point. When in doubt about whether an assistant message was a nudge vs. a reactive reply, say it's ambiguous — don't inflate the denominator.
