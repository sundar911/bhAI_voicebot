"""Shared types for the proactive agent's tool wrappers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class ToolResult:
    """Outcome of one tool call.

    `ok=True` means the tool produced its expected output (image saved,
    search results returned, etc.). `ok=False` means either the scrub layer
    rejected the input or the external API errored. `error` carries a
    human-readable reason in either failure case so the agent's critique
    pass can decide whether to retry with a different brief.
    """

    ok: bool
    tool: str  # "nanobanana" | "web_search" | "kb_read" | "tts_draft"
    artifact_path: Optional[Path] = None
    payload: Any = field(default=None)  # search results list, KB text, etc.
    error: Optional[str] = None
    scrub_reason: Optional[str] = None  # set when scrub blocked the call
