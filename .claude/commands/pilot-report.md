Generate a bhAI pilot monitoring report by pulling live data from the Railway deployment.

## Data collection

1. **Fetch dashboard metrics** using WebFetch from:
   `https://bhaivoicebot-production.up.railway.app/dashboard?key=bhai-pilot-2026`
   This returns per-user stats: message counts, response times, failures, first/last active.

2. **Fetch conversation transcripts** for each pilot user (skip phone_hash `4aabfb2a4df9` — that's Sundar testing) using WebFetch from:
   `https://bhaivoicebot-production.up.railway.app/conversations/{phone_hash}?key=bhai-pilot-2026`
   Fetch ALL users in parallel.

3. **Identify known users** by their self-introductions in conversations:
   - `6340a9665a56` = User A (Manimala)
   - `5958881a84cf` = User B
   - `118275a2cd51` = User C
   - `decaa6a18773` = User D (Sapna)
   - `f526a9d8b180` = User E (Jyoti)
   - Any new phone_hashes = label as User F, G, etc.
   - `6704c5df5504` and `0364ccdccbaf` are non-pilot (team/one-off testers) — include in stats but flag them

## Analysis

For each pilot user, analyze:

### Engagement
- Total messages sent / replies received
- Days active (which dates did they message?)
- Return rate: did they come back after day 1?
- Session patterns: what times of day do they message? How long are sessions?
- Trend: increasing, stable, or declining engagement?

### Conversation themes
Categorize each conversation segment into themes. Common ones:
- Work & productivity (output, tasks, daily routine)
- Family & relationships (children, spouse, siblings)
- Financial stress (housing, savings, loans, salary)
- Workplace conflicts (managers, colleagues, politics)
- Mental health & stress (anxiety, insomnia, feeling low)
- Government services (Aadhaar, PAN, ration card, schemes)
- Casual bonding (food, weather, greetings, daily life)
- Curiosity about bhAI (what is this app? how does it work?)

For each theme: note how many users raised it, and briefly what bhAI conveyed (1 line — NO user quotes, NO personal details).

### Interaction quality
- Did bhAI's tone shift appropriately (fun→serious, serious→fun)?
- Were responses concise (target: <150 chars for voice-note-friendly)?
- Did pop culture references land or feel forced?
- Any anti-sycophancy moments (bhAI pushed back on a bad idea)?
- Any moments where bhAI was too generic or missed emotional cues?

### Technical health
- Failure rate per user and overall (user messages with no bot reply)
- **IMPORTANT**: Most day-1 failures (Apr 13) were fixed by a redeployment on Apr 14 03:14 IST. When reporting failures, split them into:
  - **Pre-fix** (before Apr 14 03:14 IST) — historical, root cause resolved
  - **Post-fix** (after Apr 14 03:14 IST) — these are the ones that matter, investigate and flag prominently
  - Only flag post-fix failures as action items. Pre-fix failures are context, not urgency.
- Average response time per user and overall
- Any STT issues (garbled transcription, wrong language detected)?
- Any known bugs (e.g., intro message duplication on first response)?

## Report format

Write the report to `/private/tmp/bhai_pilot_report.txt` with this structure:

```
bhAI PILOT REPORT — {today's date}
Generated: {timestamp}

════════════════════════════════════════
EXECUTIVE SUMMARY
════════════════════════════════════════
- 3-5 bullet points: what's working, what's broken, what needs attention

════════════════════════════════════════
ENGAGEMENT DASHBOARD
════════════════════════════════════════
Table: User | Msgs Sent | Replies | Failed | Avg Speed | Days Active | Last Seen | Status

Overall stats: total messages, active users, avg response time, failure rate

════════════════════════════════════════
RETENTION TRACKER
════════════════════════════════════════
Which users came back on which days? Simple grid.
Flag: who's at risk of dropping off?

════════════════════════════════════════
CONVERSATION THEMES
════════════════════════════════════════
Theme | Users | bhAI's approach (1 line)
No user quotes. No personal details. Aggregated patterns only.

════════════════════════════════════════
INTERACTION QUALITY
════════════════════════════════════════
What's landing well in bhAI's personality? What needs tuning?

════════════════════════════════════════
TECHNICAL HEALTH
════════════════════════════════════════
Failure breakdown, response time trends, STT issues, bugs

════════════════════════════════════════
RECOMMENDATIONS
════════════════════════════════════════
Prioritized action items
```

## Privacy rules (CRITICAL)
- NEVER include user quotes or message content in the report
- NEVER include phone numbers (use labels: User A, User B, etc.)
- Use first names ONLY if the user introduced themselves in conversation
- Theme descriptions must be aggregate — "2 users discussed X" not "Sapna said Y"
- This report is safe to share with the broader team

If $ARGUMENTS contains a phone_hash, generate a detailed single-user report for that user only (still no quotes).
