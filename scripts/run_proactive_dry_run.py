"""Dry-run the v2 proactive thinking agent against pilot users.

Step 6c of the v2 build (tmp/v2_proactive_design.md §5). Runs the
ProactiveThinker for each pilot user across all three slots (morning,
afternoon joke, night) WITHOUT delivering anything. Writes a portfolio
of generated nudges + full traces to tmp/v2_dry_run_<date>/ for Sundar /
Sid / Vidhi to review before any live pilot.

Usage:
    uv run python scripts/run_proactive_dry_run.py

    # Only one user:
    uv run python scripts/run_proactive_dry_run.py --phone tg_xxx

    # Skip Manimala synthetic dossier (default: include):
    uv run python scripts/run_proactive_dry_run.py --no-synthetic

This makes REAL Anthropic + Gemini calls. Cost estimate per full run:
~$1 at pilot scale (2 local users + 1 synthetic).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from src.bhai.config import KNOWLEDGE_BASE_DIR, load_config  # noqa: E402
from src.bhai.memory.store import ConversationStore  # noqa: E402
from src.bhai.proactive.agent_input import AgentInput, build_agent_input  # noqa: E402
from src.bhai.proactive.dossier_loader import UserDossier  # noqa: E402
from src.bhai.proactive.thinker import (  # noqa: E402
    NudgeCandidate,
    ProactiveThinker,
    ToolRunner,
    _make_anthropic_caller,
)

IST = timezone(timedelta(hours=5, minutes=30))


def _synthetic_manimala() -> AgentInput:
    """Hand-authored Manimala dossier for the saree-business-logo spike.

    Pulled from tmp/manimala_loan_audit.md and tmp/v2_kickoff_prompt.md
    Task 1. Used so the dry-run portfolio includes the kickoff's canonical
    test case without requiring Railway prod access.
    """
    d = UserDossier(
        phone="synthetic_manimala",
        phone_hash="9844e071b1cf",  # her real production hash
        summary=(
            "Manimala runs a saree wholesale business — sources from Surat trips, "
            "sells to a WhatsApp group of 8-15 regulars + referrals. Min order ₹25k "
            "(~70 sarees), profit ₹60-70 per saree, 2-4 month inventory cycle. "
            "Daughter (22) was in a major accident September 2024, 33-day hospital "
            "stay, foot still not healed. Heavy ongoing medical debt."
        ),
        core_facts=[
            "Naam: Manimala",
            "Saree wholesale business via WhatsApp groups",
            "BC office",
        ],
        family_facts=[
            "बेटी का September 2024 में accident हुआ था, 33 दिन hospital, पैर अभी ठीक नहीं",
            "बेटी master's कर रही है, काम नहीं कर सकती",
        ],
        financial_facts=[
            "saree business चला रही हैं — Surat se wholesale source karti hain",
            "8-15 regular WhatsApp customers, min order ₹25k (~70 sarees)",
            "profit ₹60-70 per saree, 2-4 month inventory cycle",
            "पुराना loan 50,000 रुपए, EMI 5,000",
            "बेटी के accident का कर्जा अभी भी बाकी है",
            "नया loan 1 lakh sochi rahi hain Surat supplier change ke liye",
        ],
        grievance_facts=[],
        scheme_facts=[],
    )
    # No recent conversation — we're starting from cold dossier.
    return AgentInput(dossier=d, recent_messages=[])


def _run_one_user(
    thinker: ProactiveThinker,
    agent_input: AgentInput,
    *,
    label: str,
    out_dir: Path,
) -> List[NudgeCandidate]:
    """Run the three slots for one user, write per-slot JSON + return the
    list of nudge candidates."""
    user_dir = out_dir / agent_input.phone_hash
    user_dir.mkdir(parents=True, exist_ok=True)

    # Save the dossier itself so the reviewer can see what context the
    # agent worked from.
    agent_input.dossier.write_to_disk(user_dir / "dossier")

    candidates: List[NudgeCandidate] = []
    for slot, runner in (
        ("morning", lambda: thinker.think_substantive(agent_input, "morning")),
        ("afternoon", lambda: thinker.think_joke(agent_input)),
        ("night", lambda: thinker.think_substantive(agent_input, "night")),
    ):
        print(f"  [{label}] {slot}...", end=" ", flush=True)
        try:
            cand = runner()
            candidates.append(cand)
            print(f"→ {cand.category}")
        except Exception as e:
            print(f"✗ {type(e).__name__}: {e}")
            cand = NudgeCandidate(
                slot=slot,
                category="error",
                silent_day_reason=f"exception: {type(e).__name__}: {e}",
            )
            candidates.append(cand)

        # Persist full trace.
        trace_path = user_dir / f"{slot}.json"
        trace_path.write_text(
            json.dumps(_nudge_to_dict(cand), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return candidates


def _nudge_to_dict(c: NudgeCandidate) -> dict:
    """Serialise a NudgeCandidate to a dict — flattens the dataclasses
    inside (BrainstormCandidate) so json.dumps works cleanly."""
    return {
        "slot": c.slot,
        "category": c.category,
        "text": c.text,
        "artifact_path": str(c.artifact_path) if c.artifact_path else None,
        "chosen_candidate": (
            asdict(c.chosen_candidate) if c.chosen_candidate else None
        ),
        "silent_day_reason": c.silent_day_reason,
        "brainstorm_candidates": [asdict(b) for b in c.brainstorm_candidates],
        "critique_verdicts": c.critique_verdicts,
        "judge_verdict": c.judge_verdict,
        "tool_results": c.tool_results,
    }


def _write_portfolio_summary(
    out_dir: Path,
    rows: List[tuple],  # (label, phone_hash, candidates)
) -> Path:
    """Write a single PORTFOLIO.md that's the review surface for Sundar."""
    parts = [
        "# v2 Proactive Dry-Run Portfolio",
        f"\nGenerated: {datetime.now(IST).isoformat()}",
        f"\nUsers: {len(rows)}",
        "\nReview this file alongside the per-slot JSON traces in each "
        "`<phone_hash>/` subdirectory.\n",
        "---\n",
    ]

    for label, phone_hash, candidates in rows:
        parts.append(f"## {label}  \nphone_hash: `{phone_hash}`\n")
        for c in candidates:
            parts.append(f"### {c.slot} — {c.category}\n")
            if c.text:
                parts.append(f"> {c.text}\n")
            if c.artifact_path:
                parts.append(f"- **artifact**: `{c.artifact_path}`\n")
            if c.silent_day_reason:
                parts.append(f"- **silent-day reason**: {c.silent_day_reason}\n")
            if c.chosen_candidate:
                parts.append(f"- **chosen candidate**: {c.chosen_candidate.summary}\n")
                parts.append(f"- **trace**: {c.chosen_candidate.trace}\n")
                if c.chosen_candidate.tools_needed:
                    parts.append(
                        f"- **tools**: {', '.join(c.chosen_candidate.tools_needed)}\n"
                    )
            parts.append("\n")
        parts.append("---\n")

    portfolio_path = out_dir / "PORTFOLIO.md"
    portfolio_path.write_text("\n".join(parts), encoding="utf-8")
    return portfolio_path


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--phone", help="Run only this phone (default: all active local users)"
    )
    ap.add_argument(
        "--no-synthetic",
        action="store_true",
        help="Skip the synthetic Manimala dossier (default: include it)",
    )
    ap.add_argument(
        "--db", default="data/conversations.db", help="Path to local SQLite DB"
    )
    ap.add_argument(
        "--active-days",
        type=int,
        default=365,
        help="Only run users active within the last N days",
    )
    args = ap.parse_args(argv)

    cfg = load_config()
    if not cfg.anthropic_api_key:
        print("ERROR: ANTHROPIC_API_KEY missing in .env — cannot run agent loop.")
        return 1

    ts = datetime.now(IST).strftime("%Y-%m-%d_%H%M")
    out_dir = ROOT / "tmp" / f"v2_dry_run_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Writing portfolio to {out_dir}")

    # Build the thinker with real wiring.
    anth_caller = _make_anthropic_caller(cfg.anthropic_api_key)
    tool_runner = ToolRunner(
        config=cfg,
        artifacts_base_dir=out_dir / "artifacts",
        audit_base_dir=out_dir / "audit",
        kb_dir=KNOWLEDGE_BASE_DIR,
        tts=None,  # No TTS at the dry-run stage; voice notes are reviewed as text
    )
    thinker = ProactiveThinker(
        cfg,
        anthropic_caller=anth_caller,
        tool_runner=tool_runner,
        model="claude-sonnet-4-6",
    )

    rows: List[tuple] = []

    # Local users from the SQLite DB.
    db_path = ROOT / args.db
    if db_path.exists():
        store = ConversationStore(db_path)
        active = store.list_recently_active_phones(days=args.active_days)
        if args.phone:
            active = [p for p in active if p == args.phone]
        for phone in active:
            agent_input = build_agent_input(store, phone, recent_turns=20)
            label = phone if len(phone) <= 30 else phone[:30] + "…"
            print(f"\n=== {label} ({agent_input.phone_hash}) ===")
            cands = _run_one_user(thinker, agent_input, label=label, out_dir=out_dir)
            rows.append((label, agent_input.phone_hash, cands))
        store.close()
    else:
        print(f"NOTE: {db_path} not found — skipping local-DB users.")

    # Synthetic Manimala for the saree-business-logo spike.
    if not args.no_synthetic and not args.phone:
        agent_input = _synthetic_manimala()
        print(f"\n=== synthetic Manimala ({agent_input.phone_hash}) ===")
        cands = _run_one_user(
            thinker, agent_input, label="synthetic Manimala", out_dir=out_dir
        )
        rows.append(("synthetic Manimala", agent_input.phone_hash, cands))

    if not rows:
        print("No users to run.")
        return 1

    portfolio_path = _write_portfolio_summary(out_dir, rows)
    print(f"\n✓ Portfolio written: {portfolio_path}")
    print(f"  Per-slot traces in {out_dir}/<phone_hash>/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
