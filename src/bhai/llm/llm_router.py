"""
KB + use-case router driven by Claude Sonnet 4.6 with Anthropic prompt caching.

Per turn, sends the transcribed user message — plus the last 1-2 turns of
conversation history for disambiguation — to Sonnet alongside a static
list of available helpdesk topics. Sonnet returns two lines: the 1-3 most
relevant KB file stems, and zero-or-more use-case tags from a fixed
allowlist (grievance, finance, scheme_kb, general). The static prefix
carries a ``cache_control`` breakpoint so repeat calls within the 5-minute
cache TTL pay 10% of input cost.

Previously this used Haiku 4.5 (cheaper, single-turn). We switched to
Sonnet 4.6 + conversation context after a real-conversation audit
(2026-05-25 transcript) showed 3 of 10 turns tagged ∅ because short
follow-ups like "वो आँखें डाँटती रहती है" lost their grievance/scheme_kb
intent when seen in isolation. Sonnet with 1-2 turns of context closes
those misses at the cost of ~5× per-call spend (still ≪1 cent per turn
post-cache).

On any failure (network, parse, missing API key, timeout) the router
falls back to the keyword ``KBRouter`` so the voice loop never breaks.
The keyword fallback returns empty use-cases — we'd rather have no tag
than a wrong tag when the LLM router is unavailable.
"""

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

import anthropic

from .kb_router import KBRouter, RouteResult

logger = logging.getLogger("bhai.llm.llm_router")

INDEX_FILE = "_index.md"
DEFAULT_MODEL = "claude-sonnet-4-6"

# How many messages of conversation history (user + assistant interleaved)
# to include before the current user transcript. 4 = the last 2
# user-assistant exchanges. Chosen to disambiguate short follow-ups
# without burning tokens.
DEFAULT_CONTEXT_TURNS = 4

# Fixed allowlist. Anything the router LLM emits outside this set is dropped.
VALID_USE_CASES = (
    "grievance",
    "finance",
    "finance_advice",
    "scheme_kb",
    "general",
)


_ROUTER_INSTRUCTIONS = """You are a router for bhAI, a Hindi voice bot for Mumbai artisans.

You will receive the user's current transcribed voice message, and (when available) the last 1-2 turns of conversation before it. Emit exactly two lines based on the CURRENT user message, using the prior turns to disambiguate short follow-ups:

KB: <comma-separated KB file stems, 1-3, or empty>
USE_CASES: <comma-separated tags from the allowlist, or empty>

No quotes, no JSON, no explanation, no other text. Both lines must be present even if empty.

For the KB line: if the query is companion-mode chitchat (greetings, feelings, family, weather, food, daily life), output `KB: _index` only.

**Using prior turns**: a short user follow-up like "हाँ कर दो", "बस इतना ही?", "तुम भेजो", "वो आँखें डाँटती है" inherits the topical intent from the immediately preceding turn(s). If the prior assistant turn was about Aadhaar, the follow-up is still scheme_kb. If the prior turn was about a supervisor problem, the follow-up is still grievance. Don't reset to ∅ just because the current line is short.

KB topics available:
{topics}

USE_CASES allowlist (multi-label OK):
  grievance      — workplace problem, pay dispute, supervisor/co-worker conflict, harassment, family situation bleeding into work
  finance        — user asking to LOOK UP a number from their own records: salary received this month, PF balance, EPF contribution, loan repayment status, EMI auto-deducted. Data lookup, not advice.
  finance_advice — user discussing a financial DECISION: should I take this loan, is this EMI affordable, should I make this business investment, can I afford this purchase, how do I plan for X cost. ANY discussion of a loan / EMI / business investment / large purchase that calls for math (breakeven, cash-flow, debt-service ratio) is finance_advice — not just finance.
  scheme_kb      — user asking about a government scheme or document (Aadhaar, PAN, voter ID, ration card, ESIC, marriage cert, PMMY, PMJAY, Ladki Bahin, etc.) — overlaps with a non-empty KB line
  general        — everyday "stuff you'd Google": restaurants, kids' classes, brands, recipes, prices, opinions on common decisions

Leave USE_CASES empty for pure companion chitchat (greetings, "how are you", talking about food/weather/family with no specific ask).

Multi-label is allowed when the turn genuinely touches more than one: e.g. a user venting about delayed employer salary = `grievance, finance`. But don't over-tag — if the turn is clearly about one thing, emit one tag.

Examples:

Prior:
  (none)
Current: आज मन भारी है
Output:
KB: _index
USE_CASES:

Prior:
  (none)
Current: Aadhaar update kaise karu?
Output:
KB: aadhaar
USE_CASES: scheme_kb

Prior:
  User: मेरे supervisor का कुछ करना पड़ेगा, वो irritate कर रही है
  bhAI: ये कब से हो रहा है?
Current: वो आँखें डाँटती रहती है सबके सामने मुझे
Output:
KB: _index
USE_CASES: grievance

Prior:
  User: दोनों बच्चों का आधार बनवाना है
  bhAI: BC centre जाना होगा, ये documents लगेंगे...
Current: बस इतना ही? और कुछ नहीं?
Output:
KB: aadhaar
USE_CASES: scheme_kb

Prior:
  User: मुझे Priti दीदी मदद करती है सब, मैं उसको बोलूं?
  bhAI: हाँ बिल्कुल Priti को बोलो, number भेज रही हूँ
Current: अरे तुम भेजो भाई प्रीति को ईमेल, मैं क्यों भेजूँगी?
Output:
KB: _index
USE_CASES: scheme_kb

Prior:
  (none)
Current: Salary abhi tak nahi aayi, supervisor kuch bata bhi nahi raha
Output:
KB: _index
USE_CASES: grievance, finance

Prior:
  (none)
Current: BC ke paas Chinese restaurant ₹700 mein 4 logo ke liye bata
Output:
KB: _index
USE_CASES: general

Prior:
  (none)
Current: Mudra loan chahiye chhota business ke liye
Output:
KB: scheme_pmmy
USE_CASES: scheme_kb

Prior:
  (none)
Current: ₹1 lakh ka naya loan le rahi hu saree business ke liye, ₹8000 EMI hai, kar lu kya?
Output:
KB: _index
USE_CASES: finance_advice

Prior:
  User: ₹1 lakh ka naya loan le rahi hu, ₹8000 EMI hai
  bhAI: aur abhi koi EMI chal rahi hai?
Current: haan ₹5000 ka pehle ka chal raha hai, par wo khatam hone wala hai
Output:
KB: _index
USE_CASES: finance_advice

Prior:
  (none)
Current: salary slip aayi nahi abhi tak, kya hua?
Output:
KB: _index
USE_CASES: finance
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


class LLMKBRouter:
    """LLM-driven KB + use-case router using Sonnet 4.6 + prompt caching.

    The router takes the same interface as :class:`KBRouter` so callers
    can swap between them by config. ``threshold`` is accepted for
    compatibility but ignored — the LLM makes a categorical include/exclude
    decision instead of producing a score.

    Default model is Sonnet 4.6. The class accepts any Claude model id
    via ``model``; smaller models (Haiku) work but trade accuracy on
    short follow-ups for cost (see module docstring).
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
            "llm_router init: model=%s topics=%d system_chars=%d index=%s",
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
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> RouteResult:
        """Return docs to inject + use-case tags for this transcript.

        Always starts with ``_index.md`` if present. Use-case tags come
        from a fixed allowlist (see ``VALID_USE_CASES``); anything else
        the router LLM emits is silently dropped.

        ``conversation_history`` is the recent message list (same shape
        as what ``BaseLLM.generate`` receives — list of
        ``{"role": "user"|"assistant", "content": str}``). The last
        :data:`DEFAULT_CONTEXT_TURNS` entries are included before the
        current transcript so the LLM can disambiguate short follow-ups.
        Pass ``None`` (or omit) for the no-context path used by tests
        and the legacy single-turn flow.
        """
        paths: List[Path] = []
        if self._index_path is not None:
            paths.append(self._index_path)

        if not transcript.strip():
            return RouteResult(paths=paths, use_cases=[])

        messages = _build_router_messages(transcript, conversation_history)

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
                messages=messages,  # type: ignore[arg-type]
                temperature=0.0,
            )
        except Exception as e:
            logger.warning(
                "llm_router failed (%s: %s), falling back to keyword router",
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
            "llm_router decision: query=%r ctx_msgs=%d → kb=%r use_cases=%r "
            "(cache_read=%s cache_write=%s)",
            transcript[:60],
            len(messages) - 1,  # current turn excluded from "context"
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


def _build_router_messages(
    transcript: str,
    conversation_history: Optional[List[Dict[str, str]]],
) -> List[Dict[str, str]]:
    """Assemble the messages list sent to the router LLM.

    Anthropic's API requires alternating user/assistant turns starting
    with user. The conversation history (if any) is rendered as a single
    leading "user" message containing labelled prior turns, followed by
    a second "user" message with the current transcript. We render the
    history as text inside a single user message (rather than passing
    actual alternating turns) because:

    1. The router is doing classification, not multi-turn generation —
       conflating roles is fine.
    2. It keeps caching boundaries clean: only the static system prompt
       sits behind the cache_control breakpoint; everything in messages
       is fresh per turn.
    3. It avoids API errors when the history starts with assistant.
    """
    history = conversation_history or []
    context_msgs = history[-DEFAULT_CONTEXT_TURNS:] if history else []

    if not context_msgs:
        return [{"role": "user", "content": f"Current: {transcript}"}]

    prior_lines = []
    for m in context_msgs:
        role = m.get("role", "")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        label = "User" if role == "user" else "bhAI"
        prior_lines.append(f"  {label}: {content}")

    prior_block = "\n".join(prior_lines) if prior_lines else "  (none)"
    return [
        {
            "role": "user",
            "content": f"Prior:\n{prior_block}\nCurrent: {transcript}",
        }
    ]


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
