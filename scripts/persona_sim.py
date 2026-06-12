"""On-policy persona simulation driver.

Runs the CURRENT bot (reactive LLM + proactive thinker, with whatever
prompts are on disk) one step at a time against a persistent SQLite store,
so a persona player — a human, or Claude Code in-the-loop — can hold a real
conversation where the bot reacts to THIS conversation, not a recorded one.
Fixes the off-policy problem of v2_thread_replay.py (which replays fixed
human turns recorded against the OLD bot).

Each invocation is one step; state persists in /tmp/persona_sim_<phone>.db.

  uv run python scripts/persona_sim.py reset   --phone tg_manimala
  uv run python scripts/persona_sim.py react   --phone tg_manimala --text "..."
  uv run python scripts/persona_sim.py slot    --phone tg_manimala --slot morning
  uv run python scripts/persona_sim.py threads --phone tg_manimala
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

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
    ProactiveThinker,
    ToolRunner,
    _make_anthropic_caller,
)


def _db(phone: str) -> Path:
    return Path(f"/tmp/persona_sim_{phone}.db")


def _threads(store: ConversationStore, phone: str):
    return [
        (t.slug, t.state, (t.context or "")[:70]) for t in store.list_threads(phone)
    ]


def _apply_memory(store, phone, prior, patches):
    if not patches:
        return
    ns, nf = patches.get("summary"), patches.get("facts") or []
    if not ns and not nf:
        return
    es = (prior or {}).get("summary", "")
    ef = (prior or {}).get("facts", []) or []
    store.save_memory(phone, ns or es, merge_facts(ef, nf) if nf else ef)


def cmd_react(args):
    store = ConversationStore(_db(args.phone))
    sid, is_new = store.get_or_create_session(args.phone)
    store.save_message(args.phone, "user", args.text, sid)
    if store.record_nudge_reaction(args.phone, args.text):
        print("[reaction attached to most recent un-reacted nudge]")
    mem = store.get_memory(args.phone)
    msum = mem["summary"] if mem else ""
    facts = "\n".join(f"- {f}" for f in mem["facts"]) if mem else ""
    recent = store.get_recent_messages(args.phone, limit=8)
    hist = recent[:-1] if recent else []
    llm = create_llm(load_config())
    res = llm.generate_with_emotions(
        args.text,
        domain="hr_admin",
        user_profile="",
        memory_summary=msum,
        extracted_facts=facts,
        conversation_history=hist,
        is_new_session=is_new,
        mode_instruction="",
    )
    print(f"\nbhAI: {res['text']}")
    if res.get("escalate"):
        print(f"[ESCALATE: true  category={res.get('category')}]")
    else:
        print("[escalate: false]")
    store.save_message(args.phone, "assistant", res["text"], sid)
    _apply_memory(store, args.phone, mem, res.get("memory_patches"))
    tp = res.get("thread_patches") or []
    if tp:
        before = _threads(store, args.phone)
        store.apply_thread_patches(args.phone, tp)
        after = _threads(store, args.phone)
        if after != before:
            print(f"[threads] {after}")
    store.close()


def cmd_slot(args):
    store = ConversationStore(_db(args.phone))
    cfg = load_config()
    ai = build_agent_input(store, args.phone, recent_turns=20)
    thinker = ProactiveThinker(
        cfg,
        anthropic_caller=_make_anthropic_caller(cfg.anthropic_api_key),
        tool_runner=ToolRunner(
            config=cfg,
            artifacts_base_dir=Path("/tmp/persona_sim_artifacts"),
            audit_base_dir=Path("/tmp/persona_sim_audit"),
            kb_dir=KNOWLEDGE_BASE_DIR,
            tts=None,
        ),
        model="claude-sonnet-4-6",
    )
    cand = (
        thinker.think_substantive(ai, args.slot)
        if args.slot == "afternoon"
        else thinker.think_checkin(ai, args.slot)
    )
    slug = cand.chosen_candidate.thread_slug if cand.chosen_candidate else None
    print(f"\n[{args.slot} nudge — category={cand.category} thread={slug}]")
    print(f"bhAI: {cand.text}")
    if cand.text_artifact:
        print(f"\n[text artifact — rides as a SEPARATE message]\n{cand.text_artifact}")
    if cand.artifact_path:
        print(f"[image artifact: {cand.artifact_path}]")
    store.record_nudge_outcome(
        args.phone, args.slot, slug, category=cand.category, text=cand.text
    )
    store.close()


def cmd_threads(args):
    store = ConversationStore(_db(args.phone))
    for t in _threads(store, args.phone):
        print(t)
    store.close()


def cmd_reset(args):
    p = _db(args.phone)
    if p.exists():
        p.unlink()
    print(f"reset {p}")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("react", "slot", "threads", "reset"):
        sp = sub.add_parser(name)
        sp.add_argument("--phone", required=True)
        if name == "react":
            sp.add_argument("--text", required=True)
        if name == "slot":
            sp.add_argument(
                "--slot", required=True, choices=["morning", "afternoon", "night"]
            )
    args = ap.parse_args()
    {"react": cmd_react, "slot": cmd_slot, "threads": cmd_threads, "reset": cmd_reset}[
        args.cmd
    ](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
