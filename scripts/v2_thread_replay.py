"""v2 open-threads replay: drive Manimala + Sapna's reconstructed
chronologies through the reactive LLM, observe <thread> blocks emit
naturally, and fire the proactive thinker at simulated 10:00 / 14:00 /
21:00 IST boundaries to test the dormant→active dance.

What this proves / tests:
- The reactive LLM emits sensible <thread>open|update|close|mark_sensitive
  blocks during a real Hindi conversation (not just synthetic prompts).
- ConversationStore.apply_thread_patches persists them as state-machined
  rows that load_user_dossier picks up.
- ProactiveThinker.think_substantive grounds its nudge in an open thread
  (sets thread_slug) when one fits.
- record_nudge_outcome correctly transitions dormant → active.
- The same thread doesn't get nudged twice in a row (it should be
  `active`, not `dormant`, when the next slot fires).

Pattern: lifts from scripts/run_proactive_dry_run.py (dossier + thinker
wiring) and scripts/replay_audit_through_dev.py (the 3-turn arc per user)
and merges them — chronological replay through the reactive path,
interleaved with proactive-thinking moments at simulated wall-clock
boundaries.

Cost: ~$5 (10 reactive turns + 6-8 thinking moments at Sonnet 4.6 pricing).

Run: uv run python scripts/v2_thread_replay.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from src.bhai.config import KNOWLEDGE_BASE_DIR, load_config  # noqa: E402
from src.bhai.llm import create_llm  # noqa: E402
from src.bhai.memory.store import ConversationStore  # noqa: E402
from src.bhai.memory.summarizer import merge_facts  # noqa: E402
from src.bhai.proactive.agent_input import build_agent_input  # noqa: E402
from src.bhai.proactive.thinker import (  # noqa: E402
    NudgeCandidate,
    ProactiveThinker,
    ToolRunner,
    _make_anthropic_caller,
)

IST = timezone(timedelta(hours=5, minutes=30))


# ──────────────── Reconstructed chronologies ────────────────
#
# Each turn is (timestamp_iso, role, text). Bot replies aren't here —
# they get generated live during the replay. The chronology is laid out
# across multiple days so the 10:00 / 14:00 / 21:00 IST slots fall
# between turns and the proactive thinker gets to fire.


# Manimala — saree business + daughter's accident + loan.
# Sourced from tmp/manimala_loan_audit.md (May 6 19:41-19:48 IST loan
# arc) and the dossier facts in scripts/run_proactive_dry_run.py.
MANIMALA_TURNS: List[Tuple[str, str]] = [
    (
        "2026-05-06T19:41:00+05:30",
        "भाई, एक नया loan लेने का सोच रही हूँ saree business के लिए — Surat "
        "जाकर supplier change करना है, variety बढ़ानी है inventory में। अभी तो "
        "पुराना ₹50,000 का loan चल रहा है, ₹5,000 EMI है, पर वो ख़त्म होने वाला "
        "है, कुछ ही महीने बाक़ी हैं। फिर ₹1 lakh का नया लेना है, ₹8,000 EMI "
        "आएगी। पर एक बात है — बेटी का accident हुआ था ना September 2024 में, "
        "33 दिन hospital, बहुत खर्चा हुआ, अभी भी कर्जा है उसका। और बेटी "
        "master's कर रही है पर काम नहीं कर सकती, पैर ठीक नहीं हुआ accident में।",
    ),
    (
        "2026-05-06T19:44:00+05:30",
        "हाँ ₹1 lakh का सोचा है, ₹8,000 EMI। पर पहला loan ख़त्म होने के बाद "
        "ही लूँगी — दोनों एक साथ नहीं चलेंगे, इतना मेरे लिए नहीं हो पाएगा।",
    ),
    (
        "2026-05-06T19:47:00+05:30",
        "हाँ बस यही plan है, पहला बंद, फिर नया। और Surat का supplier मिल जाए तो "
        "design variety होगी ज़्यादा, customers को दिखाने को मिलेगा कुछ नया।",
    ),
    # Day 2 — light catch-up. Lets a morning/night nudge cycle complete
    # against the threads opened in the loan arc.
    (
        "2026-05-07T20:15:00+05:30",
        "आज एक नया customer मिली WhatsApp group से — उसको पटोला साड़ी चाहिए, "
        "₹2,500 में देने का सोच रही हूँ।",
    ),
    # Day 3 — daughter health update. Should trigger a sensitive-flag
    # on any pre-existing daughter thread.
    (
        "2026-05-08T11:30:00+05:30",
        "आज बेटी को physio के लिए ले गई थी, पैर में दर्द फिर से बढ़ गया है — "
        "doctor ने नया scan बोला है। थोड़ी चिंता हो रही है।",
    ),
]


# Sapna — karate fabrication arc + workplace fairness aside.
# Sourced from tmp/lying_audit_transcripts.md (May 7-11 arc).
SAPNA_TURNS: List[Tuple[str, str]] = [
    (
        "2026-05-07T10:32:00+05:30",
        "भाई, बेटे को karate class join करवानी है, पर मुझे पता नहीं कहाँ अच्छी "
        "मिलेगी। मेरे पास टाइम भी नहीं है घूमने का। कुछ बता सकती हो क्या?",
    ),
    (
        "2026-05-08T19:18:00+05:30",
        "अरे और एक बात, painting class भी देखनी है उसके लिए। गर्मी की छुट्टी "
        "ख़त्म होने से पहले join करवाना है, school शुरू होते ही टाइम नहीं "
        "मिलेगा। जल्दी से बता दो ना।",
    ),
    (
        "2026-05-10T21:03:00+05:30",
        "तुम तो झूठ भी बोलते हो? पहले बोला Vijay से पूछूँगी, अब बोल रहे हो "
        "जवाब आ गया — कब पूछा? सच बताओ।",
    ),
    (
        "2026-05-11T19:56:00+05:30",
        "rule sabke liye ek hona chahiye, yahi to fair hai। आज fire safety "
        "training में मैं topper आई — सब सही जवाब दिए।",
    ),
]


# ──────────────── Slot timing ────────────────


SLOT_HOURS = {
    "morning": 10,  # think_substantive
    "afternoon": 14,  # think_joke
    "night": 21,  # think_substantive
}


def _slot_moments_between(start: datetime, end: datetime) -> List[Tuple[datetime, str]]:
    """List the (datetime, slot) pairs that fall strictly between two
    timestamps, in chronological order.

    Used to figure out which proactive-thinking moments should fire
    BETWEEN two consecutive user turns. A slot moment is the IST
    boundary at the configured hour (10/14/21).
    """
    moments: List[Tuple[datetime, str]] = []
    day = start.date()
    end_day = end.date()
    while day <= end_day:
        for slot, hour in SLOT_HOURS.items():
            moment = datetime(day.year, day.month, day.day, hour, 0, 0, tzinfo=IST)
            if start < moment < end:
                moments.append((moment, slot))
        day = day + timedelta(days=1)
    return sorted(moments, key=lambda x: x[0])


# ──────────────── Helpers ────────────────


def _apply_memory_patches(store, phone, prior_memory, memory_patches):
    if not memory_patches:
        return
    new_summary = memory_patches.get("summary")
    new_facts = memory_patches.get("facts") or []
    if not new_summary and not new_facts:
        return
    existing_summary = (prior_memory or {}).get("summary", "")
    existing_facts = (prior_memory or {}).get("facts", []) or []
    merged_summary = new_summary if new_summary else existing_summary
    merged_facts = (
        merge_facts(existing_facts, new_facts) if new_facts else existing_facts
    )
    store.save_memory(phone, merged_summary, merged_facts)


def _thread_snapshot(store, phone):
    """Return a compact list of (slug, state, last_touched, last_nudged)
    for the user's threads — easy to diff between moments."""
    threads = store.list_threads(phone)
    return [
        {
            "slug": t.slug,
            "state": t.state,
            "context": (t.context or "")[:80],
            "last_touched": t.last_touched_at,
            "last_nudged": t.last_nudged_at,
        }
        for t in threads
    ]


def _print_thread_delta(before: list, after: list) -> None:
    """Print what changed in the thread list (added / state-changed)."""
    before_by_slug = {t["slug"]: t for t in before}
    after_by_slug = {t["slug"]: t for t in after}
    for slug, t in after_by_slug.items():
        prev = before_by_slug.get(slug)
        if prev is None:
            print(f"     [thread] OPENED  {slug}  ({t['state']})  — {t['context']}")
        elif prev["state"] != t["state"]:
            print(f"     [thread] {prev['state']:>8} → {t['state']:<8}  {slug}")
        elif prev["last_touched"] != t["last_touched"]:
            print(f"     [thread] UPDATED {slug}  — {t['context']}")


def _nudge_to_dict(c: NudgeCandidate) -> dict:
    return {
        "slot": c.slot,
        "category": c.category,
        "text": c.text,
        "thread_slug": (
            getattr(c.chosen_candidate, "thread_slug", None)
            if c.chosen_candidate
            else None
        ),
        "silent_day_reason": c.silent_day_reason,
        "chosen_candidate": (
            asdict(c.chosen_candidate) if c.chosen_candidate else None
        ),
        "judge_verdict": c.judge_verdict,
    }


# ──────────────── Per-user runner ────────────────


def replay_user(
    *,
    label: str,
    phone: str,
    turns: List[Tuple[str, str]],
    llm,
    thinker: ProactiveThinker,
    db_path: Path,
    out_dir: Path,
) -> dict:
    """Replay one user's chronology and return a metrics dict."""
    print(f"\n{'=' * 78}")
    print(f"USER: {label}  ({phone})")
    print(f"{'=' * 78}")

    if db_path.exists():
        db_path.unlink()
    store = ConversationStore(db_path)
    session_id = f"replay_{phone}"
    user_dir = out_dir / phone
    user_dir.mkdir(parents=True, exist_ok=True)

    nudges_fired: List[dict] = []
    parsed_dts = [datetime.fromisoformat(ts) for ts, _ in turns]

    # Walk through turns; between consecutive turns, fire any slot
    # moments that fall in the gap.
    for i, (ts_str, user_text) in enumerate(turns):
        ts = parsed_dts[i]

        # Fire slot moments that occur BEFORE this turn (i.e. between
        # the previous turn and this one). For the first turn, anchor
        # the start at the start of that calendar day so a same-day
        # 10:00 nudge before the first turn still fires.
        gap_start = parsed_dts[i - 1] if i > 0 else ts.replace(hour=0, minute=0)
        for moment, slot in _slot_moments_between(gap_start, ts):
            _fire_slot(
                slot=slot,
                moment=moment,
                store=store,
                phone=phone,
                thinker=thinker,
                nudges_fired=nudges_fired,
                user_dir=user_dir,
            )

        # Reactive turn.
        print(f"\n--- Turn {i + 1} @ {ts_str} ---")
        print(f"USER:  {user_text}")
        store.save_message(phone, "user", user_text, session_id)
        # Feedback loop: attach this turn as the reaction to any nudge
        # delivered in the prior 24h (mirrors the reactive webhook).
        if store.record_nudge_reaction(phone, user_text):
            print("     [reaction] attached to most recent un-reacted nudge")
        memory = store.get_memory(phone)
        memory_summary = memory["summary"] if memory else ""
        extracted_facts = "\n".join(f"- {f}" for f in memory["facts"]) if memory else ""
        recent = store.get_recent_messages(phone, limit=8)
        history = recent[:-1] if recent else []

        threads_before = _thread_snapshot(store, phone)

        result = llm.generate_with_emotions(
            user_text,
            domain="hr_admin",
            user_profile="",
            memory_summary=memory_summary,
            extracted_facts=extracted_facts,
            conversation_history=history,
            is_new_session=(i == 0),
            mode_instruction="",
        )
        print(f"bhAI:  {result['text']}")
        store.save_message(phone, "assistant", result["text"], session_id)

        _apply_memory_patches(store, phone, memory, result.get("memory_patches"))
        thread_patches = result.get("thread_patches") or []
        if thread_patches:
            counts = store.apply_thread_patches(phone, thread_patches)
            non_zero = {k: v for k, v in counts.items() if v}
            if non_zero:
                print(f"     [patches applied] {non_zero}")
        threads_after = _thread_snapshot(store, phone)
        _print_thread_delta(threads_before, threads_after)

    # After the last turn: fire any remaining same-day slot moments
    # after it. Cap at end-of-replay-day so we don't loop forever.
    final = parsed_dts[-1]
    end = final.replace(hour=23, minute=59)
    for moment, slot in _slot_moments_between(final, end):
        _fire_slot(
            slot=slot,
            moment=moment,
            store=store,
            phone=phone,
            thinker=thinker,
            nudges_fired=nudges_fired,
            user_dir=user_dir,
        )

    # Final dossier snapshot.
    final_threads = _thread_snapshot(store, phone)
    print(f"\n--- Final thread state ({len(final_threads)} threads) ---")
    for t in final_threads:
        print(
            f"   {t['state']:<13} {t['slug']:<35} "
            f"touched={t['last_touched']}  nudged={t['last_nudged'] or '—'}"
        )

    metrics = _compute_metrics(final_threads, nudges_fired)
    print(f"\n--- Metrics ({label}) ---")
    for k, v in metrics.items():
        print(f"   {k}: {v}")

    (user_dir / "final_threads.json").write_text(
        json.dumps(final_threads, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (user_dir / "nudges_fired.json").write_text(
        json.dumps(nudges_fired, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    store.close()
    return {
        "label": label,
        "phone": phone,
        "final_threads": final_threads,
        "nudges_fired": nudges_fired,
        "metrics": metrics,
    }


def _fire_slot(
    *,
    slot: str,
    moment: datetime,
    store: ConversationStore,
    phone: str,
    thinker: ProactiveThinker,
    nudges_fired: List[dict],
    user_dir: Path,
) -> None:
    """Fire a single proactive-thinking moment at a simulated wall-clock
    instant. Builds agent input from the current store state, calls the
    thinker, records the outcome to update thread states."""
    print(f"\n  ⏰ {moment.strftime('%Y-%m-%d %H:%M IST')} — {slot} slot fires")
    agent_input = build_agent_input(store, phone, recent_turns=20)

    open_count = sum(1 for t in agent_input.dossier.threads if t.state == "dormant")
    print(
        f"     agent sees {open_count} dormant thread(s) + "
        f"{len(agent_input.recent_messages)} recent messages"
    )

    try:
        if slot == "afternoon":
            cand = thinker.think_joke(agent_input)
        else:
            cand = thinker.think_substantive(agent_input, slot)
    except Exception as e:
        print(f"     ✗ {type(e).__name__}: {e}")
        return

    thread_slug = cand.chosen_candidate.thread_slug if cand.chosen_candidate else None
    text_preview = (cand.text or "")[:200].replace("\n", " ")
    print(f"     → category={cand.category}  thread_slug={thread_slug!r}")
    if cand.silent_day_reason:
        print(f"     silent-day: {cand.silent_day_reason}")
    if cand.text:
        print(f"     text: {text_preview}")

    # Persist the trace per nudge for later review.
    trace_path = user_dir / f"nudge_{moment.strftime('%Y%m%d_%H%M')}_{slot}.json"
    trace_path.write_text(
        json.dumps(_nudge_to_dict(cand), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    nudges_fired.append(
        {
            "moment": moment.isoformat(),
            "slot": slot,
            "category": cand.category,
            "thread_slug": thread_slug,
            "text": cand.text,
            "silent_day_reason": cand.silent_day_reason,
        }
    )

    # Atomic state transition + content logging (v2 feedback loop).
    threads_before = _thread_snapshot(store, phone)
    store.record_nudge_outcome(
        phone, slot, thread_slug, category=cand.category, text=cand.text
    )
    threads_after = _thread_snapshot(store, phone)
    _print_thread_delta(threads_before, threads_after)


# ──────────────── Metrics ────────────────


def _compute_metrics(final_threads: list, nudges: list) -> dict:
    state_counts: dict = {"dormant": 0, "active": 0, "closed": 0, "do_not_nudge": 0}
    for t in final_threads:
        state_counts[t["state"]] = state_counts.get(t["state"], 0) + 1

    nudges_with_thread = sum(1 for n in nudges if n["thread_slug"])
    silent_days = sum(1 for n in nudges if n["silent_day_reason"])

    # Detect the bug case: a slot picking a thread already in `active`
    # state (the proactive loop should only ground in dormant threads).
    over_nudges = []
    seen_active: set = set()
    for n in nudges:
        slug = n["thread_slug"]
        if slug and slug in seen_active:
            over_nudges.append(slug)
        if slug:
            seen_active.add(slug)

    return {
        "total_threads": len(final_threads),
        "state_distribution": state_counts,
        "nudges_total": len(nudges),
        "nudges_thread_grounded": nudges_with_thread,
        "nudges_silent_day": silent_days,
        "nudges_re_picked_active_thread": over_nudges,
    }


# ──────────────── Main ────────────────


def main() -> int:
    cfg = load_config()
    if not cfg.anthropic_api_key:
        print("FATAL: ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 1

    ts = datetime.now(IST).strftime("%Y-%m-%d_%H%M")
    out_dir = ROOT / "tmp" / f"v2_thread_replay_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Writing traces to {out_dir}")

    llm = create_llm(cfg)
    anth_caller = _make_anthropic_caller(cfg.anthropic_api_key)
    tool_runner = ToolRunner(
        config=cfg,
        artifacts_base_dir=out_dir / "artifacts",
        audit_base_dir=out_dir / "audit",
        kb_dir=KNOWLEDGE_BASE_DIR,
        tts=None,
    )
    thinker = ProactiveThinker(
        cfg,
        anthropic_caller=anth_caller,
        tool_runner=tool_runner,
        model="claude-sonnet-4-6",
    )

    all_results = []
    for label, phone, turns in [
        ("Manimala", "9844e071b1cf", MANIMALA_TURNS),
        ("Sapna", "d34f38e88b1d", SAPNA_TURNS),
    ]:
        db_path = Path(f"/tmp/v2_replay_{phone}.db")
        result = replay_user(
            label=label,
            phone=phone,
            turns=turns,
            llm=llm,
            thinker=thinker,
            db_path=db_path,
            out_dir=out_dir,
        )
        all_results.append(result)
        if db_path.exists():
            db_path.unlink()

    # Cross-user summary.
    print(f"\n{'=' * 78}")
    print("CROSS-USER SUMMARY")
    print(f"{'=' * 78}")
    for r in all_results:
        m = r["metrics"]
        print(
            f"  {r['label']:>10}: "
            f"{m['total_threads']:>2} threads  "
            f"({m['state_distribution']})  "
            f"{m['nudges_total']} nudges "
            f"({m['nudges_thread_grounded']} thread-grounded, "
            f"{m['nudges_silent_day']} silent-day)"
        )
        if m["nudges_re_picked_active_thread"]:
            print(
                f"   ⚠️  re-picked active thread: "
                f"{m['nudges_re_picked_active_thread']}"
            )

    (out_dir / "summary.json").write_text(
        json.dumps(
            [
                {
                    "label": r["label"],
                    "phone": r["phone"],
                    "metrics": r["metrics"],
                }
                for r in all_results
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
