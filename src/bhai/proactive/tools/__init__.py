"""Tool wrappers for the proactive thinking agent.

Step 4 of the v2 proactive build (see tmp/v2_proactive_design.md §3 and §12).

Every external-API tool wrapper (nanobanana, web_search) MUST call through
the privacy scrub layer (src/bhai/proactive/scrubbers/) before any network
egress and MUST write a row to the per-user tool-audit log regardless of
outcome (success / scrub-block / API-error). Internal tools (kb_read,
tts_draft) don't need scrubbing but still write audit rows so a spot-check
can see every action the agent took for a given user.
"""

from ._audit_log import ToolAuditEntry, append_audit_entry
from ._types import ToolResult

__all__ = ["ToolResult", "ToolAuditEntry", "append_audit_entry"]
