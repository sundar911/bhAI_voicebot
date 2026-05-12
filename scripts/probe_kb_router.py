"""
Probe the KB router locally without standing up Telegram.

Use:
  uv run python scripts/probe_kb_router.py                 # canned sample set
  uv run python scripts/probe_kb_router.py "query here"    # ad-hoc single query
  echo "query1\nquery2" | uv run python scripts/probe_kb_router.py -    # piped queries

Requires ANTHROPIC_API_KEY in env / .env when KB_ROUTER_BACKEND=haiku
(the default). With KB_ROUTER_BACKEND=keyword, no API call is made.

The probe shows, for each query:
- which files the router selected (and what they would contribute to the
  injected system prompt)
- total chars vs. the baseline of injecting the full helpdesk block
- Anthropic prompt-cache stats (read/write tokens) when Haiku backend
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from bhai.config import KNOWLEDGE_BASE_DIR, load_config  # noqa: E402
from bhai.llm.kb_router import KBRouter  # noqa: E402

CANNED_QUERIES = [
    "आज मन भारी है",
    "Aadhaar update kaise karu?",
    "Mera PAN khoya, kya karu?",
    "Voter ID nahin hai, kaise banwau",
    "Ration card mein name add karna hai",
    "Shaadi ka certificate kaise milega",
    "Naam galat छप गया sab cards pe",
    "Income certificate ke liye salary slip chahiye?",
    "Sukanya samriddhi yojana eligibility",
    "Mudra loan kaise milega chhota business ke liye",
    "PM Vishwakarma scheme registration",
    "Ladki Bahin yojana 1500 rupay",
    "Jan Dhan zero balance account",
    "Widow pension kaise milegi",
    "main pregnant hu, government help mil sakti hai",
    "ration shop deny kar raha hai",
]


def build_router(config):
    helpdesk_dir = KNOWLEDGE_BASE_DIR / "helpdesk"
    keyword = KBRouter(helpdesk_dir)
    backend = getattr(config, "kb_router_backend", "haiku")
    if backend == "haiku" and config.anthropic_api_key:
        from bhai.llm.haiku_router import HaikuKBRouter

        return (
            HaikuKBRouter(
                kb_dir=KNOWLEDGE_BASE_DIR,
                fallback=keyword,
                api_key=config.anthropic_api_key,
            ),
            "haiku",
        )
    return keyword, "keyword"


def baseline_chars() -> int:
    helpdesk_dir = KNOWLEDGE_BASE_DIR / "helpdesk"
    return sum(
        p.read_text(encoding="utf-8").__len__() for p in helpdesk_dir.glob("*.md")
    )


def probe(router, backend: str, queries: list[str]) -> None:
    baseline = baseline_chars()
    print(f"Backend: {backend}")
    print(f"Baseline (full helpdesk injection): {baseline:,} chars")
    print()
    total_inj = 0
    for q in queries:
        if not q.strip():
            continue
        paths = router.route(q)
        chars = sum(p.read_text(encoding="utf-8").__len__() for p in paths)
        total_inj += chars
        names = ", ".join(p.stem for p in paths) or "(none)"
        print(f"  query : {q}")
        print(f"  routed: {names}")
        print(f"  inject: {chars:,} chars  ({(1 - chars/baseline)*100:.0f}% reduction)")
        print()

    if queries:
        avg = total_inj / len(queries)
        print(
            f"Avg injection across {len(queries)} queries: {avg:,.0f} chars "
            f"(vs baseline {baseline:,}; {(1 - avg/baseline)*100:.1f}% reduction)"
        )


def main() -> None:
    config = load_config()
    router, backend = build_router(config)

    args = sys.argv[1:]
    if not args:
        queries = CANNED_QUERIES
    elif args == ["-"]:
        queries = [line.rstrip() for line in sys.stdin if line.strip()]
    else:
        queries = [" ".join(args)]

    probe(router, backend, queries)


if __name__ == "__main__":
    main()
