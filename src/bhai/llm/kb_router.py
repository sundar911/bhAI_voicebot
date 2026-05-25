"""
KB router: keyword-based document selection for system-prompt injection.

Each user turn, score every ``helpdesk/*.md`` file by Jaccard similarity
between the transcript tokens and a per-file keyword profile built at init
time. Return the top-N files above a threshold so the LLM only sees what's
relevant for this turn.

The always-on ``_index.md`` (a one-line topic summary per file) is included
on every call, giving the LLM awareness of what bhAI *can* answer even when
nothing else matches.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from ..resilience.faq_cache import _tokenize

logger = logging.getLogger("bhai.llm.kb_router")

INDEX_FILE = "_index.md"


@dataclass
class RouteResult:
    """Output of a single routing decision.

    ``paths`` is the ordered list of KB files to inject into the system
    prompt (always starts with ``_index.md`` when present). ``use_cases``
    is the set of use-case tags Haiku emitted from the fixed allowlist;
    the keyword fallback always returns an empty list here.
    """

    paths: List[Path] = field(default_factory=list)
    use_cases: List[str] = field(default_factory=list)


@dataclass
class _Profile:
    """Keyword profile for a single KB file.

    ``all_tokens`` is the full bag (stem + headings + keywords block).
    ``stem_tokens`` is the filename-stem subset, kept separate so we can
    weight stem matches higher (a file named ``aadhaar.md`` is almost
    certainly the right hit when the query mentions Aadhaar).
    """

    all_tokens: Set[str] = field(default_factory=set)
    stem_tokens: Set[str] = field(default_factory=set)


def _profile_tokens(md_path: Path) -> _Profile:
    """Build a keyword profile for a markdown file.

    Token sources:
    - filename stem split on underscore (``marriage_certificate`` → ``{marriage, certificate}``)
    - the file's ``## Keywords`` block (curated topic terms in any language)
    - the H1 title (``# ...``) only — gives a fallback signal for files without
      a Keywords block

    Section headings beyond the title are intentionally NOT indexed: they
    leak Hindi function words ("kaise", "ke", "kya") from question lines
    into every file's profile, which causes cross-file false positives.
    """
    profile = _Profile()

    stem_tokens = {p for p in md_path.stem.lower().split("_") if len(p) > 1}
    profile.stem_tokens = stem_tokens
    profile.all_tokens.update(stem_tokens)

    try:
        content = md_path.read_text(encoding="utf-8")
    except OSError:
        return profile

    title_match = re.search(r"^#\s+(.+)$", content, flags=re.MULTILINE)
    if title_match:
        profile.all_tokens.update(_tokenize(title_match.group(1)))

    keyword_match = re.search(
        r"^##\s+Keywords\s*\n(.+?)(?=\n##\s|\Z)",
        content,
        flags=re.MULTILINE | re.DOTALL,
    )
    if keyword_match:
        profile.all_tokens.update(_tokenize(keyword_match.group(1)))

    return profile


def _score(query_tokens: Set[str], profile: _Profile) -> float:
    """Containment score with a filename-stem bonus.

    base = |query ∩ all_tokens| / |query|        (0..1)
    bonus = 0.5 × |query ∩ stem_tokens| / |query| (0..0.5)
    score = base + bonus                         (0..1.5)

    Containment (vs. Jaccard) avoids penalising large docs whose union
    with a short query is dominated by the doc's own size. The stem
    bonus tie-breaks toward files whose name *is* the topic — e.g.
    a query mentioning "Aadhaar" routes to ``aadhaar.md`` even if
    other files also mention Aadhaar in passing.
    """
    if not query_tokens:
        return 0.0
    base = len(query_tokens & profile.all_tokens) / len(query_tokens)
    bonus = 0.5 * len(query_tokens & profile.stem_tokens) / len(query_tokens)
    return base + bonus


class KBRouter:
    """Keyword router over a single KB domain directory.

    Builds per-file token profiles at init time. Per call, ``route()``
    returns the top-N files whose Jaccard similarity to the transcript
    exceeds a threshold, prefixed by the always-on ``_index.md``.
    """

    def __init__(self, domain_dir: Path):
        self.domain_dir = domain_dir
        self.profiles: Dict[Path, _Profile] = {}
        self.index_path: Optional[Path] = None
        self._build()

    def _build(self) -> None:
        if not self.domain_dir.exists():
            return
        for md_path in sorted(self.domain_dir.glob("*.md")):
            if md_path.name == INDEX_FILE:
                self.index_path = md_path
                continue
            self.profiles[md_path] = _profile_tokens(md_path)
        logger.info(
            "kb_router init: domain=%s files=%d index=%s",
            self.domain_dir.name,
            len(self.profiles),
            self.index_path.name if self.index_path else "missing",
        )

    def route(
        self,
        transcript: str,
        top_n: int = 3,
        threshold: float = 0.25,
    ) -> RouteResult:
        """Return the docs to inject + (always empty) use-cases for this transcript.

        Always includes ``_index.md`` (when present) followed by up to
        ``top_n`` scored docs whose score >= threshold. The threshold is
        on a 0..1.5 scale (containment + stem bonus, see ``_score``).

        The keyword router never emits use-cases — that decision needs the
        contextual judgment Haiku provides. When the keyword router is
        running (i.e. Haiku is down), the system prompt gets no use-case
        block, which is the safer default than a wrong tag.
        """
        paths: List[Path] = []
        if self.index_path is not None:
            paths.append(self.index_path)

        query_tokens = _tokenize(transcript) if transcript else set()
        if not query_tokens or not self.profiles:
            return RouteResult(paths=paths, use_cases=[])

        scored = [
            (_score(query_tokens, prof), path) for path, prof in self.profiles.items()
        ]
        scored.sort(key=lambda x: x[0], reverse=True)

        for score, path in scored[:top_n]:
            if score >= threshold:
                paths.append(path)
                logger.debug("kb_router match: file=%s score=%.3f", path.name, score)

        return RouteResult(paths=paths, use_cases=[])
