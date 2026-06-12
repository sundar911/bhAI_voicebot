"""KB read tool for the proactive agent.

Reads files from the local `knowledge_base/helpdesk/*.md` directory — the
same KB the reactive path's KB router selects from. No scrub layer needed
because it's internal data, not an external API call. Still writes an
audit row so a spot-check can see which KB files informed each nudge.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..dossier_loader import UserDossier
from ._audit_log import ToolAuditEntry, append_audit_entry
from ._types import ToolResult


def read_kb_file(
    slug: str,
    dossier: UserDossier,
    *,
    kb_dir: Path,
    audit_base_dir: Path,
) -> ToolResult:
    """Read `kb_dir/helpdesk/<slug>.md` and return its content as the
    ToolResult payload.

    Args:
        slug: KB file stem (e.g. "aadhaar", not "aadhaar.md"). Path
            traversal guard rejects anything with "/", "..", or absolute
            paths.
        dossier: only used to attribute the audit log row.
        kb_dir: root knowledge_base directory. Usually
            `config.KNOWLEDGE_BASE_DIR`.
        audit_base_dir: usually `data/proactive/`.
    """
    audit = ToolAuditEntry(
        phone_hash=dossier.phone_hash,
        tool="kb_read",
        brief=slug,
    )

    # Path-traversal guard: KB slugs must be a simple filename component.
    if "/" in slug or ".." in slug or Path(slug).is_absolute():
        audit.api_status = f"error: invalid_slug:{slug}"
        append_audit_entry(audit_base_dir, audit)
        return ToolResult(
            ok=False,
            tool="kb_read",
            error=f"invalid_slug: {slug}",
        )

    path: Optional[Path] = None
    for candidate in (
        kb_dir / "helpdesk" / f"{slug}.md",
        kb_dir / "shared" / f"{slug}.md",
    ):
        if candidate.exists():
            path = candidate
            break

    if path is None:
        audit.api_status = f"error: not_found:{slug}"
        append_audit_entry(audit_base_dir, audit)
        return ToolResult(
            ok=False,
            tool="kb_read",
            error=f"kb_file_not_found: {slug}",
        )

    content = path.read_text(encoding="utf-8")
    audit.api_status = "ok"
    audit.artifact_path = str(path)
    append_audit_entry(audit_base_dir, audit)
    return ToolResult(
        ok=True,
        tool="kb_read",
        payload=content,
        artifact_path=path,
    )
