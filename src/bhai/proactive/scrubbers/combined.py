"""Combined entry point for the privacy scrub layer.

Run both `scrub_pii` and `scrub_content` against a candidate external-API
brief and return one merged verdict. Every external tool wrapper (step 4
of the build) MUST call this before any network egress.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from ..dossier_loader import UserDossier
from .content import scrub_content
from .pii import scrub_pii


@dataclass
class ScrubResult:
    """Merged verdict from both PII and content scrub passes."""

    ok: bool
    pii_rejected: List[str] = field(default_factory=list)
    content_rejected_categories: List[str] = field(default_factory=list)
    content_rejected_terms: List[str] = field(default_factory=list)

    def reason(self) -> str:
        """One-line summary of why the brief was rejected, for logs."""
        if self.ok:
            return "ok"
        parts: List[str] = []
        if self.pii_rejected:
            parts.append(f"pii: {', '.join(self.pii_rejected)}")
        if self.content_rejected_categories:
            cats = ", ".join(self.content_rejected_categories)
            terms = ", ".join(self.content_rejected_terms)
            parts.append(f"content[{cats}]: {terms}")
        return "; ".join(parts)


def scrub_for_external_api(brief: str, dossier: UserDossier) -> ScrubResult:
    """Run both scrub passes against `brief`. Returns ok=True iff safe.

    Wrappers around nanobanana, web search, and any future external API
    must pass through this function. The result's `.reason()` should be
    written to the per-user audit log alongside the original brief, so a
    later spot-check can see exactly what was sent, what was blocked, and
    why.
    """
    pii = scrub_pii(brief, dossier)
    content = scrub_content(brief)
    return ScrubResult(
        ok=(pii.ok and content.ok),
        pii_rejected=pii.rejected_terms,
        content_rejected_categories=content.rejected_categories,
        content_rejected_terms=content.rejected_terms,
    )
