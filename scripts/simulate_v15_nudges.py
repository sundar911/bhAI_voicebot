"""Simulate v1.5 nudges before/after the quality backport.

Pulls per-user data via the production /admin/memory/{hash} and
/conversations/{hash} endpoints (no DB sync, no encryption key
juggling, no leftover user data on disk). For each user × slot, runs
both prompts for 5 simulated days, feeding day N's generated nudge
into day N+1's recent_nudge_texts (anti-relentless test).

Usage:
    uv run python scripts/simulate_v15_nudges.py \\
        --hashes "d34f38e88b1d:sapna,9844e071b1cf:manimala"

Cost: ~$1.50 per run (5 days × 2 slots × 2 prompts × 2 users = 40 calls).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from inference.webhooks.nudges import (  # noqa: E402
    NUDGE_INSTRUCTION as NEW_NUDGE_INSTRUCTION,
)
from inference.webhooks.nudges import (  # noqa: E402
    SLOT_MORNING,
    SLOT_NIGHT,
    _slot_time_hint,
)
from src.bhai.config import load_config  # noqa: E402
from src.bhai.llm import create_llm  # noqa: E402
from src.bhai.llm.base import BaseLLM  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))

PROD_URL = "https://bhaivoicebot-production.up.railway.app"
DASHBOARD_KEY = os.getenv("DASHBOARD_KEY", "bhai-pilot-2026")

# Verbatim from the v1.5.0 tag — i.e. the NUDGE_INSTRUCTION text that
# was on `main` before this backport. Kept inline so the simulation
# can compare old-vs-new in a single process, no git-checkout dance.
OLD_NUDGE_INSTRUCTION = """\
=== Nudge Mode ===
You are starting a NEW message to the user — they did NOT message you. You're
reaching out first, like a sister who suddenly thought of them.

This is a CHECK-IN, not a request, not a survey, not a reminder. The whole point
is to feel like a friend who remembers. If you make this feel transactional, you
have failed.

Two cases — pick the right one:

**Case A — Returning user (you have memory/recent conversation history with them):**
Pick up something CONCRETE from what you remember — a person they mentioned
(बेटा/बेटी/पति/माँ), a worry, a plan, a feeling. "अरे, बेटी की तबियत कैसी अब?"
beats "कैसे हो?". Show you actually remember.
- Morning slot: warm "good morning" energy + the specific reference.
- Night slot: ease into "how was your day" + the specific reference, OR a
  reflective check-in tied to what they shared earlier.

**Case B — New user (no prior conversation, empty memory):**
Just a clean time-of-day greeting. No invented context, no fake familiarity.
- Morning slot: a warm "Good morning! कैसी हो?" / "सुप्रभात!" — keep it light
  and inviting. One short sentence.
- Night slot: "शाम हो गयी — दिन कैसा रहा आज?" / "Good evening! आज का दिन कैसा था?"
  Ask about their day. Open, no pressure.

Hard rules (both cases):
- 1-2 sentences MAX. Under 200 Devanagari characters. The voice note should be
  3-8 seconds, not 15.
- NEVER make up details. NEVER pretend to remember something you don't.
- Don't be needy. Don't say "मैं सोच रही थी आपके बारे में" or
  "बहुत दिन हो गए". No guilt-trips.
- Don't apologize for messaging. Don't ask permission to talk.
- Ask AT MOST one short question.
- No markdown. No asterisks. No bullets. Plain Devanagari sentences only.
- Match the user's number language if you mention numbers (Hindi word if they
  use Hindi, English digits if they use English).
- No "ESCALATE:" line, no "EMOTIONS_JSON:" line — just the plain text.

Output ONLY the nudge text. Nothing else.
"""

DAYS = 5


def fetch_user_input(hash_id: str) -> Dict:
    """Pull memory + recent messages via the live admin endpoints — same
    data shape production _maybe_nudge_one() sees on a real fire,
    decrypted server-side, no local encryption key needed."""
    with httpx.Client(timeout=30.0) as client:
        memory_resp = client.get(
            f"{PROD_URL}/admin/memory/{hash_id}",
            params={"key": DASHBOARD_KEY},
        )
        memory_resp.raise_for_status()
        memory = memory_resp.json()

        conv_resp = client.get(
            f"{PROD_URL}/conversations/{hash_id}",
            params={"key": DASHBOARD_KEY},
        )
        conv_resp.raise_for_status()
        all_msgs = conv_resp.json().get("messages", [])

    # Take the last 8 turns — matches production build_and_generate_nudge's
    # get_recent_messages(limit=10) closely enough; the difference is
    # immaterial for prompt-quality comparison.
    recent = all_msgs[-8:] if len(all_msgs) > 8 else all_msgs
    recent_messages = [{"role": m["role"], "content": m["content"]} for m in recent]

    return {
        "hash_id": hash_id,
        "user_profile": "",  # prod load_user_profile returns "" for every user
        "memory_summary": memory.get("summary") or "",
        "extracted_facts": "\n".join(memory.get("facts") or []),
        "recent_messages": recent_messages,
    }


def build_user_message(
    *,
    recent_messages: List[Dict[str, str]],
    recent_nudge_texts: List[str],
    slot: str,
) -> str:
    parts = []
    if recent_messages:
        parts.append("=== Recent Conversation (for context — pick up from here) ===")
        for msg in recent_messages:
            role_label = "User" if msg["role"] == "user" else "भाई (you)"
            parts.append(f"{role_label}: {msg['content']}")
        parts.append("=== End Recent Conversation ===\n")
    else:
        parts.append("(No prior conversation — keep it a casual hello.)\n")

    if recent_nudge_texts:
        parts.append("=== Recently Sent Nudges (do NOT repeat these topics) ===")
        for i, text in enumerate(recent_nudge_texts, 1):
            parts.append(f"[{i}] {text}")
        parts.append("=== End Recently Sent Nudges ===\n")

    parts.append(f"Time slot: {_slot_time_hint(slot)}.\nGenerate the nudge now.")
    return "\n".join(parts)


def generate_once(
    llm,
    instruction: str,
    user_input: Dict,
    slot: str,
    prior_nudges: List[str],
) -> str:
    system = (
        llm._build_system_prompt(
            "hr_admin",
            user_input["user_profile"],
            user_input["memory_summary"],
            user_input["extracted_facts"],
        )
        + "\n\n"
        + instruction
    )
    user = build_user_message(
        recent_messages=user_input["recent_messages"],
        recent_nudge_texts=prior_nudges,
        slot=slot,
    )
    raw = llm._call_api_with_retry(system, user)
    return BaseLLM._clean_response(raw)


def simulate_user_slot(
    llm, user_input: Dict, label: str, slot: str, out_dir: Path
) -> None:
    out_path = out_dir / f"{label}_{slot}.md"
    print(f"  {label} {slot}...", end=" ", flush=True)

    old_history: List[str] = []
    new_history: List[str] = []
    parts = [
        f"# {label} — {slot} slot — {DAYS}-day simulation",
        "",
        f"hash: `{user_input['hash_id']}`",
        f"facts: {len(user_input['extracted_facts'].splitlines())} lines",
        f"recent_messages: {len(user_input['recent_messages'])} turns",
        "",
        "---",
        "",
    ]

    for day in range(1, DAYS + 1):
        print(f"d{day}", end=" ", flush=True)
        old_nudge = generate_once(
            llm, OLD_NUDGE_INSTRUCTION, user_input, slot, old_history
        )
        new_nudge = generate_once(
            llm, NEW_NUDGE_INSTRUCTION, user_input, slot, new_history
        )
        old_history.append(old_nudge)
        new_history.append(new_nudge)

        parts.append(f"## Day {day}")
        parts.append("")
        parts.append("### OLD (v1.5 current)")
        parts.append("")
        parts.append(f"> {old_nudge}")
        parts.append("")
        parts.append("### NEW (this backport)")
        parts.append("")
        parts.append(f"> {new_nudge}")
        parts.append("")
        parts.append("---")
        parts.append("")

    out_path.write_text("\n".join(parts), encoding="utf-8")
    print("✓")


def parse_hashes(arg: str) -> List[Tuple[str, str]]:
    pairs = []
    for token in arg.split(","):
        token = token.strip()
        if not token:
            continue
        if ":" not in token:
            raise ValueError(f"--hashes entry missing ':' — got {token!r}")
        hash_id, label = token.split(":", 1)
        pairs.append((hash_id.strip(), label.strip()))
    return pairs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--hashes",
        required=True,
        help=(
            "Comma-separated <hash>:<label> pairs, e.g. "
            "'d34f38e88b1d:sapna,9844e071b1cf:manimala'"
        ),
    )
    args = ap.parse_args()

    cfg = load_config()
    if cfg.llm_backend != "claude" or not cfg.anthropic_api_key:
        print(
            "ERROR: simulation needs LLM_BACKEND=claude + ANTHROPIC_API_KEY set in .env"
        )
        return 1

    pairs = parse_hashes(args.hashes)
    llm = create_llm(cfg)
    ts = datetime.now(IST).strftime("%Y-%m-%d_%H%M")
    out_dir = ROOT / "tmp" / f"v1.5_nudge_simulation_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Writing comparison to {out_dir}\n")

    for hash_id, label in pairs:
        print(f"Fetching {label} ({hash_id})...", end=" ", flush=True)
        user_input = fetch_user_input(hash_id)
        print(
            f"✓ ({len(user_input['recent_messages'])} msgs, "
            f"{len(user_input['extracted_facts'].splitlines())} facts)"
        )
        for slot in (SLOT_MORNING, SLOT_NIGHT):
            simulate_user_slot(llm, user_input, label, slot, out_dir)

    print(f"\n✓ Done. Read tmp/v1.5_nudge_simulation_{ts}/ — one file per user×slot.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
