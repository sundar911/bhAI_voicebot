"""Build a structured per-user dossier from the existing SQLite memory store.

Step 1 of the v2 proactive build (see tmp/v2_proactive_design.md §12). The
proactive thinking agent needs more structure than the v1.5 monolithic facts
blob — it needs facts bucketed by domain so the brainstorm pass can cycle
through under-explored domains instead of latching onto whatever's salient.

This module reads from the existing ConversationStore and produces an in-memory
`UserDossier` whose markdown files mirror the design doc's proposed
`data/memories/<phone_hash>/*.md` layout. No disk migration of the SQLite store —
the SQLite store stays authoritative; this is a read-only structured view.

The bucketing is multi-label keyword-based for v1: a fact about a daughter's
hospital bill goes to both family_context AND financial_threads. The agent
prompt then sees the fact in every domain where it's relevant.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

from ..memory.store import IST, ConversationStore
from .threads import Thread

# ── Bucket definitions ──────────────────────────────────────────────────

# Each entry: (bucket_name, list of regex patterns matched against lowercased fact)
# Multi-label is intentional — a fact can land in multiple buckets.
_BUCKET_PATTERNS: List[tuple[str, List[str]]] = [
    (
        "family_context",
        [
            # Devanagari family terms.
            r"बेट[ाीे]",
            r"बच्च[ाेीों]",
            r"पति",
            r"पत्नी",
            r"माँ",
            r"माता",
            r"पिता",
            r"\bबाप\b",
            r"सास",
            r"ससुर",
            r"भाई",
            r"बहन",
            r"शादी",
            # Romanized Hindi family terms. Note: we deliberately do NOT match
            # standalone romanized "bhai" because it collides with the bot's
            # own name ("bhAI"). Devanagari "भाई" above catches actual brother
            # references in Devanagari-written facts; romanized brother refs
            # use "brother" (caught below) or "bhaiya" (added here).
            r"\bbet[ai]\b",
            r"\bbachch?[aei]\b",
            r"\bbacche\b",
            r"\bpati\b",
            r"\bpatni\b",
            r"\bmaa\b",
            r"\bmummy\b",
            r"\bpapa\b",
            r"\bbaap\b",
            r"\bbhaiya\b",
            r"\bbehan\b",
            r"\bbehen\b",
            r"\bsasur(al)?\b",
            r"\bsaas\b",
            r"\bshaadi\b",
            r"\btabiy?eyat\b",
            r"\btabiyat\b",
            # English family terms.
            r"\bson\b",
            r"\bdaughter\b",
            r"\bchild(ren)?\b",
            r"\bkid(s)?\b",
            r"\bhusband\b",
            r"\bwife\b",
            r"\bpartner\b",
            r"\bmom\b",
            r"\bdad\b",
            r"\bmother\b",
            r"\bfather\b",
            r"\bparent",
            r"\bin-law",
            r"\bin laws?\b",
            r"\bbrother\b",
            r"\bsister\b",
            r"\bsibling",
            r"\bwedding\b",
            r"\bmarriage\b",
            r"\bschool\b",
            r"\bcollege\b",
            r"master'?s",
            r"\beducation\b",
            r"\bhospital\b",
            r"\baccident\b",
            r"\binjur(y|ed|ies)\b",
            # Devanagari education/health.
            r"स्कूल",
            r"कॉलेज",
            r"पढ़?ाई",
            r"शिक्षा",
            r"बीमार",
            r"अस्पताल",
            r"तबि?यत",
            r"दर्द",
            r"घायल",
        ],
    ),
    (
        "financial_threads",
        [
            r"\bloan\b",
            r"\bEMI\b",
            r"ईएमआई",
            r"क़?र्ज़?ा?",
            r"उधार",
            r"\bborrow",
            r"\bsalary\b",
            r"सैलरी",
            r"वेतन",
            r"\bPF\b",
            r"पीएफ",
            r"\bbhavishya nidhi\b",
            r"saree\s*business",
            r"व्यापार",
            r"धंधा",
            r"काम[- ]?धंधा",
            r"व्यवसाय",
            r"रुपए",
            r"रुपये",
            r"₹",
            r"\blakh\b",
            r"लाख",
            r"hazaar",
            r"हज़ार",
            r"\bthousand\b",
            r"\bhazar\b",
            r"\brupees?\b",
            r"\bpaise\b",
            r"\bprofit\b",
            r"\bloss\b",
            r"घाटा",
            r"फायदा",
            r"आमदनी",
            r"\bincome\b",
            r"\bearn(ing)?s?\b",
            r"कमाई",
        ],
    ),
    (
        "grievance_log",
        [
            r"\bsupervisor\b",
            r"सुपरवाइज़र",
            r"\bmanager\b",
            r"\bboss\b",
            r"\bharass",
            r"\birritat",
            r"परेशान",
            r"डाँट",
            r"डांट",
            r"\bcomplaint\b",
            r"शिकायत",
            r"\bworkplace\b",
            r"\bloom\b",
            r"लूम",
            r"\bstitch(ing)?\b",
            r"\bfold(ing)?\b",
            r"piece[- ]?rate",
            r"\bdeduction\b",
            r"salary\s*cut",
            r"\bargue\b",
            r"\bfight\b",
            r"झगड़ा",
            r"लड़ाई",
            r"\btension\b",
        ],
    ),
    (
        "scheme_status",
        [
            r"\baadh?aar\b",
            r"आधार",
            # "Ladki Bahin" is the Maharashtra women's welfare scheme.
            # Users say it colloquially as "लाड़की भाई" (literally girl-brother,
            # a near-homophone for "Bahin") so we match both forms. The family
            # pattern will also hit "भाई" in the colloquial form, so the fact
            # multi-labels into scheme + family — fine, both are legit reads.
            r"ladki\s*bah?in",
            r"ladki\s*bhai",
            r"लाड़की\s*बहिन",
            r"लाड़की\s*भाई",
            r"लाडकी\s*भाई",
            r"लाडकी\s*बहीन",
            r"\bscheme\b",
            r"योजना",
            r"\byojana\b",
            r"niramaya",
            r"निरमय",
            r"\bUDID\b",
            r"disability\s*certificate",
            r"विकलांगता",
            r"विकलांग",
            r"\bration\b",
            r"राशन",
            r"\bgovt\b",
            r"सरकार",
            r"\bgovernment\b",
            r"\bsarkari\b",
            r"दस्तावेज़",
            r"\bcertificate\b",
            r"प्रमाण",
            r"\bPriti\b",
            r"\bDinesh\b",
            r"\bAnu\b",
            r"\bRishi\b",
            r"\bSarfaraz\b",
            r"\bVidhi\b",
        ],
    ),
]

# Identity patterns — facts matching these also land in core.md so the
# always-loaded layer always carries name/work-location/community.
_IDENTITY_PATTERNS = [
    r"\bnaam\b",
    r"\bname\b",
    r"\bनाम\b",
    r"\bkaam\b",
    r"\bwork\b",
    r"\bकाम\b",
    r"\bBC\s*office\b",
    r"\bMIDC\s*office\b",
    r"\bAarey\b",
    r"\bPardhi\b",
    r"\bcommunity\b",
    r"\bसमुदाय\b",
]

# Pre-compile for speed and case-insensitive matching.
_BUCKET_COMPILED: List[tuple[str, List[re.Pattern]]] = [
    (name, [re.compile(p, re.IGNORECASE) for p in pats])
    for name, pats in _BUCKET_PATTERNS
]
_IDENTITY_COMPILED = [re.compile(p, re.IGNORECASE) for p in _IDENTITY_PATTERNS]


def classify_fact(fact: str) -> Set[str]:
    """Return the set of bucket names this fact belongs to.

    A fact can land in zero or more domain buckets (family_context,
    financial_threads, grievance_log, scheme_status) plus optionally "core"
    if it matches an identity pattern. Facts that match no domain bucket
    fall through to "core" as a catch-all.
    """
    buckets: Set[str] = set()
    for name, patterns in _BUCKET_COMPILED:
        if any(p.search(fact) for p in patterns):
            buckets.add(name)

    if any(p.search(fact) for p in _IDENTITY_COMPILED):
        buckets.add("core")

    # Catch-all: facts that hit no domain bucket land in core so the agent
    # still sees them on every thinking pass.
    if not buckets:
        buckets.add("core")

    return buckets


# ── Dossier data class ─────────────────────────────────────────────────


@dataclass
class UserDossier:
    """Structured per-user dossier — the agent's view of one user's memory.

    Each `_facts` field is a list of fact strings classified into that domain.
    The `.markdown_map()` method renders them into the {filename: content}
    dict the agent prompt assembles into context.
    """

    phone: str
    phone_hash: str
    summary: str
    core_facts: List[str] = field(default_factory=list)
    family_facts: List[str] = field(default_factory=list)
    financial_facts: List[str] = field(default_factory=list)
    grievance_facts: List[str] = field(default_factory=list)
    scheme_facts: List[str] = field(default_factory=list)
    threads: List[Thread] = field(default_factory=list)

    def _render_bullets(self, facts: List[str], empty_placeholder: str) -> str:
        if not facts:
            return empty_placeholder
        return "\n".join(f"- {f}" for f in facts)

    def _render_threads(self) -> str:
        """Render the open-threads section: dormant first (most actionable
        for the next nudge), then active (recently nudged — watch the
        reaction window), then do_not_nudge (situational awareness only;
        the brainstorm prompt is told to skip these). Closed threads are
        hidden by default — they live in the SQLite history but don't
        clutter the agent's prompt.

        Each thread renders as one bullet with state, the latest context,
        and the elapsed-days hints the brainstorm pass uses to decide
        what's stale-but-revisitable. Days are computed against ``now``
        in IST so a thread last touched yesterday reads as "1d ago"
        rather than as the raw ISO timestamp.
        """
        if not self.threads:
            return "_no curiosities tracked yet_"

        order = {"dormant": 0, "active": 1, "do_not_nudge": 2, "closed": 3}
        visible = [t for t in self.threads if t.state != "closed"]
        visible.sort(key=lambda t: (order.get(t.state, 9), t.last_touched_at))

        if not visible:
            return "_no curiosities tracked yet_"

        now = datetime.now(IST)
        sections: Dict[str, List[str]] = {
            "dormant": [],
            "active": [],
            "do_not_nudge": [],
        }
        for thread in visible:
            sections.setdefault(thread.state, []).append(
                self._render_thread_line(thread, now)
            )

        out: List[str] = []
        if sections.get("dormant"):
            out.append("**Dormant — eligible for the next nudge:**")
            out.extend(sections["dormant"])
        if sections.get("active"):
            if out:
                out.append("")
            out.append("**Active — recently nudged, watch for reaction:**")
            out.extend(sections["active"])
        if sections.get("do_not_nudge"):
            if out:
                out.append("")
            out.append("**Sensitive — do NOT nudge (await user re-raise):**")
            out.extend(sections["do_not_nudge"])
        return "\n".join(out)

    @staticmethod
    def _render_thread_line(thread: Thread, now: datetime) -> str:
        """One bullet describing a thread. Includes elapsed days since
        last touch (and since last nudge, if ever nudged) so the
        brainstorm pass can prefer dormant threads stale ≥14d."""
        parts = [f"`{thread.slug}`"]
        if thread.context:
            parts.append(f"— {thread.context}")
        touched_days = _days_since(thread.last_touched_at, now)
        if touched_days is not None:
            parts.append(f"(last touched {touched_days}d ago)")
        if thread.last_nudged_at:
            nudged_days = _days_since(thread.last_nudged_at, now)
            if nudged_days is not None:
                parts.append(f"(nudged {nudged_days}d ago)")
        return "- " + " ".join(parts)

    def markdown_map(self) -> Dict[str, str]:
        """Render the dossier as the {filename: markdown} dict matching the
        design doc's `data/memories/<phone_hash>/*.md` layout.

        Files that have no content yet (nudge_history, open_threads,
        outreach_history, artifacts) are included with placeholder content so
        the agent always sees the full file set and learns the layout.
        """
        h = self.phone_hash
        return {
            "core.md": (
                f"# Core — {h}\n\n"
                f"Always-loaded identity + top-of-mind facts. "
                f"Read this on every thinking pass.\n\n"
                + self._render_bullets(self.core_facts, "_no core facts yet_")
            ),
            "narrative.md": (
                f"# Narrative — {h}\n\n"
                f"Rolling Hindi summary of the user across all conversations.\n\n"
                + (self.summary.strip() or "_no narrative yet_")
            ),
            "family_context.md": (
                f"# Family Context — {h}\n\n"
                + self._render_bullets(self.family_facts, "_no family facts yet_")
            ),
            "financial_threads.md": (
                f"# Financial Threads — {h}\n\n"
                f"Loans, EMI, salary, business, money topics. "
                f"NEVER ship any of this to an external API without scrubbing.\n\n"
                + self._render_bullets(self.financial_facts, "_no financial facts yet_")
            ),
            "grievance_log.md": (
                f"# Grievance Log — {h}\n\n"
                f"Workplace issues, supervisor problems, piece-rate disputes.\n\n"
                + self._render_bullets(self.grievance_facts, "_no grievance facts yet_")
            ),
            "scheme_status.md": (
                f"# Scheme Status — {h}\n\n"
                f"Govt schemes mentioned, applications, document state, "
                f"impact-team contacts.\n\n"
                + self._render_bullets(self.scheme_facts, "_no scheme facts yet_")
            ),
            # The four placeholder files — empty until the proactive agent
            # starts populating them in later build steps.
            "outreach_history.md": (
                f"# Outreach History — {h}\n\n_no escalations recorded yet_"
            ),
            "nudge_history.md": (
                f"# Nudge History — {h}\n\n_no proactive nudges delivered yet_"
            ),
            "open_threads.md": (
                f"# Open Threads — {h}\n\n"
                "Durable curiosities bhAI is following across days. "
                "Dormant threads stale ≥14d are the highest-priority "
                "candidates for the next nudge.\n\n" + self._render_threads()
            ),
        }

    def write_to_disk(self, base_dir: Path) -> Path:
        """Write the dossier to `base_dir/<phone_hash>/*.md`. Debug-only —
        the agent reads `markdown_map()` directly in-process. Useful for
        Sundar to spot-check what the loader produces for a real user.
        """
        out_dir = base_dir / self.phone_hash
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, content in self.markdown_map().items():
            (out_dir / name).write_text(content, encoding="utf-8")
        return out_dir


# ── Loader entry point ────────────────────────────────────────────────


def _hash_phone(phone: str) -> str:
    """12-char hex prefix of SHA-256(phone). Matches the hashing pattern used
    elsewhere in the codebase for log correlation and the design doc's
    `<phone_hash>` directory layout.
    """
    return hashlib.sha256(phone.encode("utf-8")).hexdigest()[:12]


def _days_since(iso_ts: Optional[str], now: datetime) -> Optional[int]:
    """Whole IST days between ``iso_ts`` and ``now``. Returns None if the
    timestamp is missing or unparseable so the renderer can omit the
    "Nd ago" suffix gracefully."""
    if not iso_ts:
        return None
    try:
        ts = datetime.fromisoformat(iso_ts)
    except ValueError:
        return None
    return max(0, (now - ts).days)


def load_user_dossier(store: ConversationStore, phone: str) -> UserDossier:
    """Read the user's memory from the SQLite store and build a structured
    dossier with facts bucketed by domain.

    Returns a dossier with empty facts lists if the user has no memory yet —
    the agent should still get a well-formed object back, just one whose
    `markdown_map()` is full of `_no … yet_` placeholders.
    """
    mem = store.get_memory(phone)
    summary = mem["summary"] if mem else ""
    facts = mem["facts"] if mem else []

    dossier = UserDossier(
        phone=phone,
        phone_hash=_hash_phone(phone),
        summary=summary,
    )

    for fact in facts:
        for bucket in classify_fact(fact):
            if bucket == "core":
                dossier.core_facts.append(fact)
            elif bucket == "family_context":
                dossier.family_facts.append(fact)
            elif bucket == "financial_threads":
                dossier.financial_facts.append(fact)
            elif bucket == "grievance_log":
                dossier.grievance_facts.append(fact)
            elif bucket == "scheme_status":
                dossier.scheme_facts.append(fact)

    # Open threads — durable curiosities. Closed threads are loaded into
    # the dossier object so callers can inspect them if needed, but the
    # markdown renderer hides them from the agent's prompt.
    dossier.threads = store.list_threads(phone)

    return dossier
