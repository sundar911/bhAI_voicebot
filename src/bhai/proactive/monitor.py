"""Central monitoring of the proactive nudge surface.

Two responsibilities, both reading the same source of truth (the encrypted
``messages`` transcript + the ``nudge_log`` feedback table):

1. ``reconstruct_nudge_log`` — a one-off migration that seeds ``nudge_log``
   for pilot users who pre-date the feedback loop. dev's earlier
   ``backfill_nudge_history`` reconstructed nudge TEXT only; this also pairs
   each nudge with the user's REACTION (the first user message inside the
   reaction window), so the relentlessness gate and the analysis below have
   real engagement data to read.

2. ``analyze_user`` / ``analyze_portfolio`` — the offline portfolio pass.
   Given a user's reconstructed nudge_log, an LLM characterises whether the
   nudges are landing: engagement rate, what topics draw replies, what reads
   as noise, and one concrete change. This is the seed of the central
   "does the user find utility?" supervisor — offline and recommendations-
   only for now (it never edits prompts or sends nudges itself).

Both run server-side where the DB lives (``railway run`` or the admin
endpoint), never against a populated profile locally.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from bhai.llm.base import BaseLLM
    from bhai.memory.store import ConversationStore

IST = timezone(timedelta(hours=5, minutes=30))

# Slot labels — the stable strings stored in nudge_log.slot. Mirror the
# constants in inference.webhooks.nudges; defined here so this library-layer
# module doesn't import UP into the app/webhook layer (which also avoids a
# mypy dual-module-name collision).
SLOT_MORNING = "morning"
SLOT_AFTERNOON = "afternoon"
SLOT_NIGHT = "night"

# A reconstructed nudge is an assistant message that (a) lands inside a slot
# window and (b) follows a gap — i.e. it wasn't a reactive reply that merely
# happened to fall in the window. Mirrors dev's backfill heuristic.
MIN_GAP_MINUTES = 30

# How long after a nudge a user message still counts as a reaction to it.
# Matches ConversationStore.record_nudge_reaction's live 24h window.
REACTION_WINDOW_HOURS = 24

# Historical nudges have no stored category; the analysis reads text+reaction,
# not category, so a single provenance label is enough.
_BACKFILL_CATEGORY = "general"


@dataclass
class ReconcileCounts:
    """Per-phone tally from a reconstruction pass."""

    scanned: int = 0
    nudges: int = 0
    with_reaction: int = 0
    inserted: int = 0
    skipped_existing: int = 0


def _classify_slot(ts: datetime, cfg) -> Optional[str]:
    """Return the slot label for ``ts`` (morning/afternoon/night) or None."""
    ist_ts = ts.astimezone(IST)
    hour, minute = ist_ts.hour, ist_ts.minute
    window = cfg.nudge_window_minutes
    if minute > window:
        return None
    if hour == cfg.nudge_morning_hour_ist:
        return SLOT_MORNING
    if hour == getattr(cfg, "nudge_afternoon_hour_ist", -1):
        return SLOT_AFTERNOON
    if hour == cfg.nudge_night_hour_ist:
        return SLOT_NIGHT
    return None


def _is_nudge(
    messages: List[Dict[str, str]], idx: int, cfg
) -> Tuple[bool, Optional[str]]:
    """Return (is_nudge, slot) for the message at ``idx``."""
    m = messages[idx]
    if m["role"] != "assistant":
        return False, None
    ts = datetime.fromisoformat(m["timestamp"])
    slot = _classify_slot(ts, cfg)
    if slot is None:
        return False, None
    if idx == 0:
        return True, slot
    prev_ts = datetime.fromisoformat(messages[idx - 1]["timestamp"])
    if (ts - prev_ts) > timedelta(minutes=MIN_GAP_MINUTES):
        return True, slot
    return False, None


def _find_reaction(
    messages: List[Dict[str, str]], nudge_idx: int
) -> Optional[Dict[str, str]]:
    """First user message after the nudge, within the reaction window.

    Returns the message dict (content + timestamp) or None. Stops at the next
    nudge-shaped assistant message so a later nudge's reply can't be misread
    as this one's.
    """
    nudge_ts = datetime.fromisoformat(messages[nudge_idx]["timestamp"])
    deadline = nudge_ts + timedelta(hours=REACTION_WINDOW_HOURS)
    for j in range(nudge_idx + 1, len(messages)):
        nxt = messages[j]
        nxt_ts = datetime.fromisoformat(nxt["timestamp"])
        if nxt_ts > deadline:
            return None
        if nxt["role"] == "user":
            return nxt
        # An assistant message before any user reply means the user stayed
        # silent through to the next bot turn — no reaction to this nudge.
        return None
    return None


def reconstruct_nudge_log_for_phone(
    store: "ConversationStore",
    phone: str,
    cfg,
    cutoff_iso: str,
    *,
    dry_run: bool = False,
) -> ReconcileCounts:
    """Seed nudge_log for one phone from its message transcript."""
    rows = store._conn.execute(
        """SELECT role, content_enc, timestamp FROM messages
           WHERE phone = ? AND timestamp >= ?
           ORDER BY timestamp ASC""",
        (phone, cutoff_iso),
    ).fetchall()
    if not rows:
        return ReconcileCounts()

    messages = [
        {"role": r[0], "content": store._decrypt(r[1]), "timestamp": r[2]} for r in rows
    ]
    counts = ReconcileCounts(scanned=len(messages))

    for i in range(len(messages)):
        is_n, slot = _is_nudge(messages, i, cfg)
        if not is_n or slot is None:
            continue
        counts.nudges += 1
        reaction = _find_reaction(messages, i)
        if reaction is not None:
            counts.with_reaction += 1
        if dry_run:
            counts.inserted += 1
            continue
        row_id = store.backfill_nudge_log(
            phone,
            slot,
            category=_BACKFILL_CATEGORY,
            text=messages[i]["content"],
            delivered_at=messages[i]["timestamp"],
            reaction=reaction["content"] if reaction else None,
            reacted_at=reaction["timestamp"] if reaction else None,
        )
        if row_id is None:
            counts.skipped_existing += 1
        else:
            counts.inserted += 1
    return counts


def reconstruct_nudge_log(
    store: "ConversationStore",
    cfg,
    *,
    days: int = 30,
    dry_run: bool = False,
) -> Dict[str, ReconcileCounts]:
    """Run the reconstruction across every phone with recent assistant turns.

    Returns ``{phone: ReconcileCounts}`` for phones that had ≥1 nudge.
    """
    cutoff_iso = (datetime.now(IST) - timedelta(days=days)).isoformat()
    phones = [
        r[0]
        for r in store._conn.execute(
            """SELECT DISTINCT phone FROM messages
               WHERE role = 'assistant' AND timestamp >= ?""",
            (cutoff_iso,),
        ).fetchall()
    ]
    out: Dict[str, ReconcileCounts] = {}
    for phone in phones:
        counts = reconstruct_nudge_log_for_phone(
            store, phone, cfg, cutoff_iso, dry_run=dry_run
        )
        if counts.nudges:
            out[phone] = counts
    return out
