"""Sarvam TTS wrapper for the proactive agent.

Thin shim over the existing src/bhai/tts/sarvam_tts.py used on the reactive
path. The agent generates the voice-note text via the brainstorm/critique/
draft prompts, then this wrapper synthesizes it and saves to the user's
artifacts directory.

NO privacy scrub. Sarvam is an existing trusted vendor for the reactive
path (which sends PII like the user's name daily without scrubbing); the
proactive path inherits that trust posture. The text is also pre-vetted
by the agent's judge pass (step 6 — coming later) before reaching this
function. Audit row still written every call.

NOTE: this wrapper takes a generic TTS instance (any object with a
`.synthesize(text, output_path)` method) so tests can inject a fake
without standing up the full Sarvam client. In production the agent
loop builds a `SarvamTTS(config)` once and passes it in.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from ..dossier_loader import UserDossier
from ._audit_log import ToolAuditEntry, append_audit_entry
from ._types import ToolResult

IST = timezone(timedelta(hours=5, minutes=30))


class TTSLike(Protocol):
    """Minimal interface the TTS wrapper depends on. SarvamTTS satisfies it;
    tests inject a fake."""

    def synthesize(self, text: str, output_path: Path) -> Any: ...


def synthesize(
    text: str,
    dossier: UserDossier,
    *,
    tts: TTSLike,
    artifacts_dir: Path,
    audit_base_dir: Path,
    extension: str = "wav",
) -> ToolResult:
    """Synthesize `text` to a voice-note file and return its path.

    Args:
        text: the voice-note text the agent has drafted and the judge has
            approved. Sent verbatim to the TTS backend.
        dossier: only used to attribute the audit log row.
        tts: a TTS instance (usually `SarvamTTS(config)`).
        artifacts_dir: where to save the audio (usually
            `data/proactive/<phone_hash>/artifacts/`).
        audit_base_dir: usually `data/proactive/`.
        extension: file extension for the audio output. Sarvam returns WAV
            by default; some downstream paths re-encode to .opus before
            Telegram delivery.
    """
    audit = ToolAuditEntry(
        phone_hash=dossier.phone_hash,
        tool="tts_draft",
        # Truncate brief in the audit log — a 60-second voice note's text
        # is a lot to write per call, and the full text is recoverable from
        # the nudge_queue.json entry anyway.
        brief=text[:200] + ("…" if len(text) > 200 else ""),
        extra={"text_len_chars": len(text)},
    )

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
    output_path = artifacts_dir / f"{ts}_tts.{extension}"

    try:
        tts.synthesize(text, output_path)
    except Exception as e:
        audit.api_status = f"error: {type(e).__name__}: {e}"
        append_audit_entry(audit_base_dir, audit)
        return ToolResult(ok=False, tool="tts_draft", error=f"tts_error: {e}")

    if not output_path.exists():
        # The TTS call returned without raising but didn't produce a file —
        # treat as a soft failure rather than silently succeeding.
        audit.api_status = "error: no_output_file"
        append_audit_entry(audit_base_dir, audit)
        return ToolResult(ok=False, tool="tts_draft", error="tts_no_output_file")

    audit.api_status = "ok"
    audit.artifact_path = str(output_path)
    append_audit_entry(audit_base_dir, audit)
    return ToolResult(ok=True, tool="tts_draft", artifact_path=output_path)
