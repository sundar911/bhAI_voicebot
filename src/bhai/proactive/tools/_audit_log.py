"""Per-user tool-call audit log.

Every proactive agent action — successful or blocked — appends one JSON
line to `data/proactive/<phone_hash>/tool_audit.jsonl`. The log is the
spot-check surface Sundar reads after each dry-run portfolio review to
see exactly what the agent tried, what got scrubbed, and what the
external APIs returned.

The format is JSON Lines (one event per line, append-only) so we can
`tail -f` it during a live spike and `jq` it for post-hoc analysis.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

IST = timezone(timedelta(hours=5, minutes=30))


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


@dataclass
class ToolAuditEntry:
    """One row of the tool-call audit log."""

    timestamp: str = field(default_factory=_now_iso)
    phone_hash: str = ""
    tool: str = ""
    brief: str = ""  # input the agent passed to the tool
    scrubbed_ok: bool = True
    scrub_reason: Optional[str] = None
    api_status: str = "ok"  # "ok" | "blocked" | "error: …"
    artifact_path: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


def append_audit_entry(
    base_dir: Path,
    entry: ToolAuditEntry,
) -> Path:
    """Append `entry` to the per-user audit log under
    `base_dir/<phone_hash>/tool_audit.jsonl`. Returns the log path.

    Creates parent directories as needed. Caller is responsible for
    deciding which `base_dir` (usually `data/proactive` for production,
    a tmp_path in tests).
    """
    user_dir = base_dir / entry.phone_hash
    user_dir.mkdir(parents=True, exist_ok=True)
    log_path = user_dir / "tool_audit.jsonl"
    line = json.dumps(asdict(entry), ensure_ascii=False)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return log_path
