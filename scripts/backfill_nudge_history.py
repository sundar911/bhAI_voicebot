"""One-shot backfill of `nudge_history` from existing message transcripts.

Context: the v1.5 nudge-quality backport (commit 70eb0f4) added a new
`nudge_history` table that the new prompt's anti-relentless block reads
from. The table is empty for every user the moment the deploy lands —
which means the first nudge fire after deploy has no dedup signal, even
though the actual nudges ARE recorded in the messages transcript.

This script seeds nudge_history from the messages table for every user
who has nudge-shaped assistant messages in their history.

How a "nudge" is identified in the messages table:
  1. Assistant-role message.
  2. Timestamp falls inside a configured nudge slot window
     (morning ~10:00-10:30 IST, night ~21:00-21:30 IST).
  3. The previous chronological message for that phone is more than
     `MIN_GAP_MINUTES` minutes earlier — which rules out reactive
     replies that happen to land inside a nudge window.

The script is idempotent — `list_nudge_history_keys()` is consulted so
re-runs skip rows already inserted.

Usage (Railway prod):
    railway run --service web -- uv run python scripts/backfill_nudge_history.py

Usage (dry run, prints what WOULD be inserted, writes nothing):
    railway run --service web -- uv run python scripts/backfill_nudge_history.py --dry-run

Usage (local dev DB):
    uv run python scripts/backfill_nudge_history.py --db data/conversations.db
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from inference.webhooks.nudges import SLOT_MORNING, SLOT_NIGHT  # noqa: E402
from src.bhai.config import load_config  # noqa: E402
from src.bhai.memory.store import ConversationStore  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))

# How far back to scan. 30 days is generous — the dedup window the prompt
# uses is 14 days, so backfilling 30 means even the oldest dedup-relevant
# nudges are seeded.
BACKFILL_DAYS = 30

# Minimum gap between previous message and a candidate nudge for the
# candidate to be classified as a nudge (vs reactive reply). 30 min covers
# the case where a user replies inside the nudge firing window.
MIN_GAP_MINUTES = 30


def _classify_slot(ts: datetime, cfg) -> str | None:
    """Return SLOT_MORNING / SLOT_NIGHT / None for `ts`.

    Uses the configured nudge windows (default morning 10:00-10:30,
    night 21:00-21:30). Anything outside both windows returns None.
    """
    ist_ts = ts.astimezone(IST)
    hour = ist_ts.hour
    minute = ist_ts.minute
    window = cfg.nudge_window_minutes

    if hour == cfg.nudge_morning_hour_ist and minute <= window:
        return SLOT_MORNING
    if hour == cfg.nudge_night_hour_ist and minute <= window:
        return SLOT_NIGHT
    return None


def _is_nudge(
    messages: List[Dict[str, str]],
    idx: int,
    cfg,
) -> Tuple[bool, str | None]:
    """Return (is_nudge, slot) for the message at `idx`.

    A message is classified as a nudge when:
      - It's an assistant message
      - Its timestamp falls inside a nudge slot window
      - The previous chronological message is > MIN_GAP_MINUTES earlier
        (i.e., not a reactive reply to a user turn)
    """
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


def _backfill_for_phone(
    store: ConversationStore,
    phone: str,
    cfg,
    cutoff_iso: str,
    dry_run: bool,
) -> Dict[str, int]:
    """Backfill nudge_history rows for one phone. Returns counts."""
    # Pull the last 30 days of messages chronologically. We use a large
    # limit (200) which matches the existing /conversations endpoint cap.
    rows = store._conn.execute(
        """SELECT role, content_enc, timestamp FROM messages
           WHERE phone = ? AND timestamp >= ?
           ORDER BY timestamp ASC""",
        (phone, cutoff_iso),
    ).fetchall()

    if not rows:
        return {"scanned": 0, "candidates": 0, "inserted": 0, "skipped_existing": 0}

    messages = [
        {"role": r[0], "content": store._decrypt(r[1]), "timestamp": r[2]} for r in rows
    ]
    existing_keys = store.list_nudge_history_keys(phone)

    candidates = 0
    inserted = 0
    skipped = 0

    for i, m in enumerate(messages):
        is_n, slot = _is_nudge(messages, i, cfg)
        if not is_n or slot is None:
            continue
        candidates += 1
        if (slot, m["timestamp"]) in existing_keys:
            skipped += 1
            continue
        if dry_run:
            inserted += 1
            print(
                f"  [DRY] {phone[:12]} {slot:7s} {m['timestamp'][:16]} "
                f"→ {m['content'][:80]}"
            )
            continue
        store.record_nudge_text(phone, slot, m["content"], at=m["timestamp"])
        inserted += 1

    return {
        "scanned": len(messages),
        "candidates": candidates,
        "inserted": inserted,
        "skipped_existing": skipped,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--db",
        default=None,
        help="SQLite path. Defaults to config DATA_DIR/conversations.db "
        "(/app/data/conversations.db on Railway).",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print candidate rows but write nothing to the DB.",
    )
    ap.add_argument(
        "--days",
        type=int,
        default=BACKFILL_DAYS,
        help=f"How many days of history to scan. Default {BACKFILL_DAYS}.",
    )
    args = ap.parse_args()

    cfg = load_config()
    if args.db:
        db_path = Path(args.db)
    else:
        # Match production layout (Railway volume /app/data) — load_config's
        # DATA_DIR resolves correctly in both local and Railway environments.
        from src.bhai.config import DATA_DIR

        db_path = DATA_DIR / "conversations.db"

    if not db_path.exists():
        print(f"ERROR: {db_path} not found.")
        return 1

    print(f"DB: {db_path}")
    print(
        f"Slots: morning={cfg.nudge_morning_hour_ist:02d}:00, "
        f"night={cfg.nudge_night_hour_ist:02d}:00, "
        f"window={cfg.nudge_window_minutes}min"
    )
    print(f"Backfill window: last {args.days} days")
    print(f"Mode: {'DRY RUN (no writes)' if args.dry_run else 'WRITE'}\n")

    store = ConversationStore(db_path)
    cutoff_iso = (datetime.now(IST) - timedelta(days=args.days)).isoformat()

    # Find every phone with at least one assistant message in the window —
    # those are the only phones that could have nudges to backfill.
    phones = [
        r[0]
        for r in store._conn.execute(
            """SELECT DISTINCT phone FROM messages
               WHERE role = 'assistant' AND timestamp >= ?""",
            (cutoff_iso,),
        ).fetchall()
    ]
    print(f"Found {len(phones)} phones with assistant messages in window.\n")

    totals = {"scanned": 0, "candidates": 0, "inserted": 0, "skipped_existing": 0}

    for phone in phones:
        counts = _backfill_for_phone(store, phone, cfg, cutoff_iso, args.dry_run)
        if counts["candidates"] == 0:
            continue
        print(
            f"{phone[:30]:30s}  scanned={counts['scanned']:4d}  "
            f"candidates={counts['candidates']:3d}  "
            f"inserted={counts['inserted']:3d}  "
            f"skipped={counts['skipped_existing']:3d}"
        )
        for k in totals:
            totals[k] += counts[k]

    print(
        f"\n{'='*72}\n"
        f"TOTAL  scanned={totals['scanned']}  "
        f"candidates={totals['candidates']}  "
        f"inserted={totals['inserted']}  "
        f"skipped_existing={totals['skipped_existing']}"
    )
    if args.dry_run:
        print("\n(DRY RUN — no writes were made. Re-run without --dry-run to commit.)")
    else:
        print("\n✓ Backfill complete. nudge_history is now seeded for these users.")

    store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
