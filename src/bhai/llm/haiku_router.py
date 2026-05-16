"""
KB router driven by Claude Haiku 4.5 with Anthropic prompt caching.

Per turn, sends the transcribed user message to Haiku alongside a static
list of available helpdesk topics. Haiku returns the 1-3 most relevant
file stems. The static prefix carries a ``cache_control`` breakpoint so
repeat calls within the 5-minute cache TTL pay 10% of input cost.

On any failure (network, parse, missing API key, timeout) the router
falls back to the keyword ``KBRouter`` so the voice loop never breaks.
"""

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

import anthropic

from .kb_router import KBRouter

logger = logging.getLogger("bhai.llm.haiku_router")

INDEX_FILE = "_index.md"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"


_ROUTER_INSTRUCTIONS = """You are a KB router for bhAI, a Hindi voice bot for Mumbai artisans.

Given a user's transcribed voice message (Hindi, Hinglish, or Marathi), return the file stems of the 1-3 most relevant helpdesk topics.

Format: comma-separated file stems on a single line. No quotes, no JSON, no explanation. If unsure, prefer fewer topics.

If the query is companion-mode chitchat (greetings, feelings, family, weather, food, work, daily life), return only:
_index

Available topics:
{topics}

For ambiguous queries about identity / document mistakes (e.g. "naam galat hai"), return 2-3 candidate topics.

Examples:
Query: आज मन भारी है
Output: _index

Query: Aadhaar update kaise karu?
Output: aadhaar

Query: Mudra loan chahiye chhota business ke liye
Output: scheme_pmmy

Query: main pregnant hu, government help mil sakti hai?
Output: scheme_pmmvy, scheme_pmjay

Query: naam galat छप गया sab cards pe
Output: aadhaar, gazette, pan_card

Query: ration shop deny kar raha hai mereko
Output: ration_card
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
    ) -> List[Path]:
        """Return docs to inject. Always starts with ``_index.md`` if present."""
        results: List[Path] = []
        if self._index_path is not None:
            results.append(self._index_path)

        if not transcript.strip():
            return results

        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=80,
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

        logger.info(
            "haiku_router decision: query=%r → %r (cache_read=%s cache_write=%s)",
            transcript[:60],
            raw_output,
            getattr(response.usage, "cache_read_input_tokens", None),
            getattr(response.usage, "cache_creation_input_tokens", None),
        )

        stems = [s.strip().lower() for s in raw_output.split(",")]
        for stem in stems:
            if stem in ("", "_index"):
                continue
            p = self._stem_to_path.get(stem)
            if p and p not in results:
                results.append(p)
            if len(results) >= top_n + 1:  # +1 for the always-on index
                break

        return results
