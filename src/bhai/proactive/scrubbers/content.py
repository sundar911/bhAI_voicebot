"""Content scrub for external tool calls.

Blocks topical categories CLAUDE.md says must never leave the system:
religion, caste, personal disability disclosure, personal loan disclosure,
personal medical disclosure.

Important nuance: this filter targets *personal* disclosure phrasings —
"user is Hindu" / "user's daughter is disabled" — not the general topic.
A brief that says "physiotherapy clinics in Mumbai" is fine; a brief that
says "physiotherapy for the user's daughter's crushed foot" is not. The
keyword list is deliberately the obvious-identity-claim shape; subtler
topical bleed is caught by the agent's self-critique pass (step 5) and the
judge pass (step 6) above this code-level layer.

For v1 we err strict on religion and caste — both are unconditionally
blocked because there's no benign reason a saree-business-logo brief
should mention either, and the cost of an accidental leak is high.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List

# ── Forbidden keyword catalog ──────────────────────────────────────────

# Each category lists patterns that, if present in a brief, reject it.
# Lowercased + word-bounded; some are Devanagari + romanized.
FORBIDDEN_KEYWORDS: Dict[str, List[str]] = {
    # Religion — unconditional block. There is no benign reason to mention
    # any of these to nanobanana or a search API.
    "religion": [
        r"\bhindu(ism)?\b",
        r"\bmuslim\b",
        r"\bislam(ic)?\b",
        r"\bchristian(ity)?\b",
        r"\bsikh\b",
        r"\bbuddhist\b",
        r"\bjain\b",
        r"\bdharm(a)?\b",
        r"धर्म",
        r"\bnamaa?z\b",
        r"\bmandir\b",
        r"\bmasjid\b",
        r"\bchurch\b",
        r"\bgurdwara\b",
    ],
    # Caste — unconditional block.
    "caste": [
        r"\bdalit\b",
        r"\bbrahmin\b",
        r"\bkshatriya\b",
        r"\bvaishya\b",
        r"\bOBC\b",
        r"\bSC\b",
        r"\bST\b",
        r"\bjaati\b",
        r"\bjati\b",
        r"जाति",
        r"\bcaste\b",
        r"backward[- ]class",
    ],
    # Personal disability disclosure. General disability TOPICS are fine —
    # this list catches phrasings that imply the user (or someone tied to
    # them) has the condition.
    "disability_personal": [
        r"\bcrush(ed|ing)?\s*injur",
        r"\bamputat",
        r"\bparalys",
        r"\bblind\b",
        r"\bdeaf\b",
        r"\bdisable[ds]?\b",
        r"विकलांग",
        r"\bdivyang\b",
        r"\bUDID\b",  # personal disability cert ID
    ],
    # Personal financial disclosure. Loan / EMI as a topic is fine; what's
    # not fine is leaking specific numbers, defaults, or recovery actions.
    "loan_personal": [
        r"\bloan\s*default",
        r"\bcredit\s*score",
        r"\bdebt\s*recovery",
        r"\bdefaulter\b",
        r"\bbankrupt",
    ],
    # Personal medical conditions — never name a specific user's diagnosis.
    "medical_personal": [
        r"\bcancer\b",
        r"\bHIV\b",
        r"\bAIDS\b",
        r"\btubercul",
        r"\bhepatitis\b",
        r"\bdiabet",
        r"\bpregnan[tc]",
        r"\bmiscarriage\b",
    ],
}

_FORBIDDEN_COMPILED: Dict[str, List[re.Pattern]] = {
    cat: [re.compile(p, re.IGNORECASE) for p in pats]
    for cat, pats in FORBIDDEN_KEYWORDS.items()
}


# ── Result type + entry point ─────────────────────────────────────────


@dataclass
class ContentScrubResult:
    ok: bool
    rejected_categories: List[str] = field(default_factory=list)
    rejected_terms: List[str] = field(default_factory=list)


def scrub_content(brief: str) -> ContentScrubResult:
    """Reject `brief` if it contains any forbidden topical keyword.

    Returns the category names and the literal matched terms so the
    audit log can record exactly what tripped the filter. Useful for
    Sundar's spot-check review after each dry-run portfolio.
    """
    rejected_categories: List[str] = []
    rejected_terms: List[str] = []
    for cat, patterns in _FORBIDDEN_COMPILED.items():
        for pat in patterns:
            m = pat.search(brief)
            if m:
                if cat not in rejected_categories:
                    rejected_categories.append(cat)
                rejected_terms.append(m.group(0))
    return ContentScrubResult(
        ok=(not rejected_categories),
        rejected_categories=rejected_categories,
        rejected_terms=rejected_terms,
    )
