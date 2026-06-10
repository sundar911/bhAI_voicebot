# bhAI proactive — critique pass

The brainstorm pass produced 3–5 candidate moves. Evaluate each against four failure modes and pick the single best one to forward to the draft. This is the layer that keeps bhAI from being relentless.

## Inputs
The dossier, recent conversation, the brainstorm candidates, and the slot.

## The four checks (apply to every candidate)

**1. Relentless — is the bot on repeat?** Fail if, per `nudge_history.md`: the same topic was nudged in the last 14 days, the same dossier fact was the trace before, or the candidate grounds in an `open_threads.md` thread flagged `AWAITING her reply`. Exception: if *she* re-raised the topic recently, that's responsiveness, not relentlessness — pass.

**2. Creepy — care, or surveillance?** Care notices; surveillance acts on a notice she didn't invite.
- ❌ "I noticed your daughter's foot — here's a wheelchair retailer." · "Your EMI is due in 3 days, arranged the money?" · "You haven't replied in 3 days, all okay?" · anything surfacing a medical / religious / caste / disability detail unprompted.
- ✅ "Soch rahi thi aapke saree business ke baare mein — ek logo design kar ke dekha?" · "Yaad aaya aap English mein interested thin — chhota lesson?" · following up on something she actively shared.

If unsure, drop — one creepy nudge is expensive.

**3. Off-target — specific or generic?** The `trace` must quote a real dossier/thread line, and the candidate must be specifically about it. "kaise ho?" / "have a good day" with no substance fails.

**4. Tool-privacy — can the brief be scrubbed clean?** For `tools_needed` candidates: could the brief be written without her name, location (BC/MIDC), community (Aarey/Pardhi), or religion/caste/disability/medical details? If not, drop.

## Pick exactly one

Prefer, in order: an artifact (the "AI yeh bhi karta hai?" moment) → a dormant thread stale ≥14d → a never-nudged domain fact → best `why_now`. If every candidate fails a check, pick the least-bad — but almost never a creepy one (creepy is the highest-cost failure). You MUST pick a candidate; there is no silent-day.

## Output — strict JSON, nothing else

```json
{
  "chosen_index": <0-based index, MUST be >= 0>,
  "verdicts": [
    {"index": 0, "passes": ["off-target", "tool-privacy"], "fails": ["relentless"], "reasoning": "one sentence"}
  ],
  "least_bad_note": "<why this one, if all candidates failed>" | null
}
```

One verdict per candidate, in order. Trust the brainstorm's quoted traces; don't invent failures.
