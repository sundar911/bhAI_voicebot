"""PII scrub for external tool calls.

Catches:
- Indian-format mobile numbers
- Internal location markers (BC / MIDC office)
- Tiny Miracles community names (Aarey, Pardhi)
- Tiny Miracles impact-team staff names (Priti, Dinesh, Anu, Rishi, Sarfaraz, Vidhi)
- The specific user's name as extracted from their dossier's core facts

Each match blocks the brief — the agent must regenerate. We don't redact
silently because a redacted brief is often still leaky (the surrounding
context implies what's missing), and an outright reject forces the agent's
critique pass to learn what's safe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

from ..dossier_loader import UserDossier

# ── Static patterns ────────────────────────────────────────────────────

# Indian mobile numbers — 10 digits starting 6/7/8/9.
_PHONE_PATTERN = re.compile(r"\b[6-9]\d{9}\b")

# Internal location markers. "BC" and "MIDC" are Tiny Miracles' two
# workshop locations; they should never leave the system.
_LOCATION_PATTERNS = [
    re.compile(r"\bBC\s*(office|side|area)?\b", re.IGNORECASE),
    re.compile(r"\bMIDC\s*(office|side|area)?\b", re.IGNORECASE),
]

# Community names and impact-team staff names.
_INTERNAL_NAMES = [
    "Aarey",
    "Pardhi",
    "Priti",
    "Dinesh",
    "Anu",
    "Rishi",
    "Sarfaraz",
    "Vidhi",
    "Tiny Miracles",
]
_INTERNAL_NAME_PATTERNS = [
    re.compile(rf"\b{re.escape(n)}\b", re.IGNORECASE) for n in _INTERNAL_NAMES
]


# ── Name extraction from dossier ───────────────────────────────────────


# Matches "Naam: X", "Name: X", "नाम: X" — the conventional way bhAI's
# memory layer records the user's name.
_NAME_FACT_PATTERN = re.compile(
    r"(?:naam|name|नाम)\s*[:\-]\s*([^\s,]+)",
    re.IGNORECASE,
)


def extract_name_terms(dossier: UserDossier) -> List[str]:
    """Return likely name strings to block from leaving the system.

    Reads `dossier.core_facts` for "Naam: X" / "Name: X" patterns. The bot
    sometimes records names without that prefix; this function is necessarily
    conservative (won't catch every form) but blocks the obvious ones.
    """
    names: List[str] = []
    for fact in dossier.core_facts:
        m = _NAME_FACT_PATTERN.search(fact)
        if m:
            candidate = m.group(1).strip()
            # Skip trivial/short matches that would over-block — names
            # we care about are 3+ chars.
            if len(candidate) >= 3:
                names.append(candidate)
    return names


# ── Result type + entry point ─────────────────────────────────────────


@dataclass
class PiiScrubResult:
    """Outcome of running PII patterns against a candidate external brief."""

    ok: bool
    rejected_terms: List[str] = field(default_factory=list)


def scrub_pii(brief: str, dossier: UserDossier) -> PiiScrubResult:
    """Reject `brief` if it contains any user PII.

    The user's own name is extracted dynamically from the dossier so the
    same code works for every user. Phone numbers, location markers,
    community/staff names are checked against fixed patterns.
    """
    rejected: List[str] = []

    if _PHONE_PATTERN.search(brief):
        rejected.append("phone_number")

    for pat in _LOCATION_PATTERNS:
        if pat.search(brief):
            rejected.append(f"location:{pat.pattern}")

    for pat in _INTERNAL_NAME_PATTERNS:
        m = pat.search(brief)
        if m:
            rejected.append(f"internal_name:{m.group(0)}")

    for name in extract_name_terms(dossier):
        if re.search(rf"\b{re.escape(name)}\b", brief, re.IGNORECASE):
            rejected.append(f"user_name:{name}")

    return PiiScrubResult(ok=(not rejected), rejected_terms=rejected)
