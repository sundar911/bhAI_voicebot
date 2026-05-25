"""
KB router driven by Claude Haiku 4.5 with Anthropic prompt caching.

Per turn, sends the transcribed user message to Haiku alongside a static
list of available helpdesk topics. Haiku returns two lines: the 1-3 most
relevant KB file stems, and zero-or-more use-case tags from a fixed
allowlist (grievance, finance, scheme_kb, general). The static prefix
carries a ``cache_control`` breakpoint so repeat calls within the 5-minute
cache TTL pay 10% of input cost.

On any failure (network, parse, missing API key, timeout) the router
falls back to the keyword ``KBRouter`` so the voice loop never breaks.
The keyword fallback returns empty use-cases — we'd rather have no tag
than a wrong tag when Haiku is unavailable.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import anthropic

from .kb_router import KBRouter, RouteResult

logger = logging.getLogger("bhai.llm.haiku_router")

INDEX_FILE = "_index.md"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# Fixed allowlist. Anything Haiku emits outside this set is dropped.
VALID_USE_CASES = ("grievance", "finance", "scheme_kb", "general")


_ROUTER_INSTRUCTIONS = """You are a router for bhAI, a Hindi voice bot for Mumbai artisans.

Given a user's transcribed voice message (Hindi, Hinglish, or Marathi), emit exactly two lines:

KB: <comma-separated KB file stems, 1-3, or empty>
USE_CASES: <comma-separated tags from the allowlist, or empty>

No quotes, no JSON, no explanation, no other text. Both lines must be present even if empty.

For the KB line: if the query is companion-mode chitchat (greetings, feelings, family, weather, food, daily life), output `KB: _index` only.

KB topics available:
{topics}

USE_CASES allowlist (multi-label OK):
  grievance   — workplace problem, pay dispute, supervisor/co-worker conflict, harassment, family situation bleeding into work
  finance     — user asking about their OWN salary, PF, EPF, loan repayment, EMI, salary slip (NOT general money advice)
  scheme_kb   — user asking about a government scheme or document (Aadhaar, PAN, voter ID, ration card, ESIC, marriage cert, PMMY, PMJAY, etc.) — overlaps with a non-empty KB line
  general     — everyday "stuff you'd Google": restaurants, kids' classes, brands, recipes, prices, opinions on common decisions

Leave USE_CASES empty for pure companion chitchat (greetings, "how are you", talking about food/weather/family with no specific ask).

Multi-label is allowed when the turn genuinely touches more than one: e.g. a user venting about delayed salary = `grievance, finance`.

Examples:

Query: आज मन भारी है
Output:
KB: _index
USE_CASES:

Query: Aadhaar update kaise karu?
Output:
KB: aadhaar
USE_CASES: scheme_kb

Query: Salary abhi tak nahi aayi, supervisor kuch bata bhi nahi raha
Output:
KB: _index
USE_CASES: grievance, finance

Query: Mera PF balance kitna hai?
Output:
KB: _index
USE_CASES: finance

Query: BC ke paas Chinese restaurant ₹700 mein 4 logo ke liye bata
Output:
KB: _index
USE_CASES: general

Query: naam galat छप गया sab cards pe
Output:
KB: aadhaar, gazette, pan_card
USE_CASES: scheme_kb

Query: Mudra loan chahiye chhota business ke liye
Output:
KB: scheme_pmmy
USE_CASES: scheme_kb
"""


def _read_title_and_keywords(md_path: Path) -> str:
    """Build a one-line topic descriptor from a file's H1 + first keywords line."""
    try:
        content = md_path.read_text(encoding="utf-8")
    except OSError:
        return md_path.stem

    title_match = re.search(r"^#\s+(.+)$", content, flags=re.MULTILINE)
    title = title_match.group(1).strip() if title_match else md_path.stem

    kw_match = re.search(
        r"^##\s+Keywords\s*\n(.+?)(?=\n##\s|\Z)",
        content,
        flags=re.MULTILINE | re.DOTALL,
    )
    keywords = ""
    if kw_match:
        first_line = kw_match.group(1).strip().split("\n")[0]
        keywords = first_line.strip()

    return f"{title} — {keywords}" if keywords else title


class HaikuKBRouter:
    """LLM-driven KB router using Haiku 4.5 + prompt caching.

    The router takes the same interface as :class:`KBRouter` so callers
    can swap between them by config. ``threshold`` is accepted for
    compatibility but ignored — Haiku makes a categorical include/exclude
    decision instead of producing a score.
    """

    def __init__(
        self,
        kb_dir: Path,
        fallback: KBRouter,
        api_key: str,
        model: str = DEFAULT_MODEL,
        timeout_s: float = 4.0,
        client: Optional[anthropic.Anthropic] = None,
    ):
        self.kb_dir = kb_dir
        self.helpdesk_dir = kb_dir / "helpdesk"
        self.fallback = fallback
        self.model = model
        self.timeout_s = timeout_s
        self._client = client or anthropic.Anthropic(api_key=api_key, timeout=timeout_s)

        self._index_path: Optional[Path] = None
        self._stem_to_path: Dict[str, Path] = {}
        self._scan_files()

        self._system_prompt = _ROUTER_INSTRUCTIONS.format(
            topics=self._build_topic_list()
        )
        logger.info(
            "haiku_router init: model=%s topics=%d system_chars=%d index=%s",
            self.model,
            len(self._stem_to_path),
            len(self._system_prompt),
            self._index_path.name if self._index_path else "missing",
        )

    def _scan_files(self) -> None:
        if not self.helpdesk_dir.exists():
            return
        for md in sorted(self.helpdesk_dir.glob("*.md")):
            if md.name == INDEX_FILE:
                self._index_path = md
                continue
            self._stem_to_path[md.stem] = md

    def _build_topic_list(self) -> str:
        lines = []
        for stem in sorted(self._stem_to_path.keys()):
            desc = _read_title_and_keywords(self._stem_to_path[stem])
            lines.append(f"  {stem} — {desc}")
        return "\n".join(lines)

    def route(
        self,
        transcript: str,
        top_n: int = 3,
        threshold: float = 0.0,
    ) -> RouteResult:
        """Return docs to inject + use-case tags for this transcript.

        Always starts with ``_index.md`` if present. Use-case tags come
        from a fixed allowlist (see ``VALID_USE_CASES``); anything else
        Haiku emits is silently dropped.
        """
        paths: List[Path] = []
        if self._index_path is not None:
            paths.append(self._index_path)

        if not transcript.strip():
            return RouteResult(paths=paths, use_cases=[])

        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=120,
                system=[
                    {
                        "type": "text",
                        "text": self._system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": transcript}],
                temperature=0.0,
            )
        except Exception as e:
            logger.warning(
                "haiku_router failed (%s: %s), falling back to keyword router",
                type(e).__name__,
                e,
            )
            return self.fallback.route(transcript, top_n=top_n)

        # Duck-typed on the SDK's `type` discriminator so both real TextBlock
        # instances and SimpleNamespace mocks in tests work the same way.
        # mypy can't narrow on the string equality so we silence union-attr here.
        raw_output = ""
        for block in response.content:
            if getattr(block, "type", None) == "text":
                raw_output = block.text.strip()  # type: ignore[union-attr]
                break

        kb_line, use_cases_line = _split_router_output(raw_output)

        logger.info(
            "haiku_router decision: query=%r → kb=%r use_cases=%r "
            "(cache_read=%s cache_write=%s)",
            transcript[:60],
            kb_line,
            use_cases_line,
            getattr(response.usage, "cache_read_input_tokens", None),
            getattr(response.usage, "cache_creation_input_tokens", None),
        )

        stems = [s.strip().lower() for s in kb_line.split(",")]
        for stem in stems:
            if stem in ("", "_index"):
                continue
            p = self._stem_to_path.get(stem)
            if p and p not in paths:
                paths.append(p)
            if len(paths) >= top_n + 1:  # +1 for the always-on index
                break

        use_cases: List[str] = []
        for raw in use_cases_line.split(","):
            tag = raw.strip().lower()
            if tag in VALID_USE_CASES and tag not in use_cases:
                use_cases.append(tag)

        return RouteResult(paths=paths, use_cases=use_cases)


def _split_router_output(raw: str) -> tuple:
    """Parse the two-line router output, tolerating mild format drift.

    Expected:
        KB: a, b
        USE_CASES: x, y

    Both labels are case-insensitive, and either may be missing. If the
    model emits a single bare line (legacy single-output mode), treat it
    as the KB line and leave use-cases empty.
    """
    kb_line = ""
    use_cases_line = ""
    saw_label = False
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        m = re.match(r"^(KB|USE_CASES)\s*:\s*(.*)$", stripped, flags=re.IGNORECASE)
        if not m:
            continue
        saw_label = True
        label = m.group(1).upper()
        value = m.group(2).strip()
        if label == "KB":
            kb_line = value
        elif label == "USE_CASES":
            use_cases_line = value
    # Fallback: model returned only the old bare comma-separated stem list.
    if not saw_label and raw.strip():
        kb_line = raw.strip().splitlines()[0]
    return kb_line, use_cases_line
