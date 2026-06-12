"""nanobanana — Google Gemini image generation wrapper for the proactive
agent (kickoff naming for the gemini-2.5-flash-image model).

Generates an image from a *scrubbed* brief and saves it as a PNG under
`data/proactive/<phone_hash>/artifacts/`. The artifact path goes into the
nudge queue alongside the voice-note text the agent drafts to introduce it
(see Manimala saree-business-logo flow in tmp/v2_proactive_design.md §5).

Hard contract: every call passes through `scrub_for_external_api` first.
If the scrub blocks, NO network call happens. Every attempt — clean call,
scrub block, or API error — writes one row to the per-user audit log so
Sundar can spot-check what the agent tried.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import httpx

from ..dossier_loader import UserDossier
from ..scrubbers import scrub_for_external_api
from ._audit_log import ToolAuditEntry, append_audit_entry
from ._types import ToolResult

logger = logging.getLogger("bhai.proactive.nanobanana")

IST = timezone(timedelta(hours=5, minutes=30))

# Type alias for the HTTP transport — injected in tests so we don't hit the
# real API. Signature matches `httpx.post(url, json=..., timeout=...)`.
HttpPostFn = Callable[..., httpx.Response]


def generate_image(
    brief: str,
    dossier: UserDossier,
    *,
    api_key: str,
    model: str,
    endpoint: str,
    artifacts_dir: Path,
    audit_base_dir: Path,
    http_post: Optional[HttpPostFn] = None,
    request_timeout: float = 60.0,
) -> ToolResult:
    """Generate an image from `brief` for the user described by `dossier`.

    Args:
        brief: textual prompt for the image. MUST be scrub-safe — caller
            is responsible for ensuring the brief was generated against
            the privacy rules. We re-run the scrub here as defense-in-depth.
        dossier: the user's dossier — needed for the scrub layer to know
            which name(s) to block.
        api_key: Gemini API key (config.nanobanana_api_key).
        model: model name (config.nanobanana_model).
        endpoint: API base URL (config.nanobanana_endpoint).
        artifacts_dir: where to save the generated PNG. Usually
            `data/proactive/<phone_hash>/artifacts/`.
        audit_base_dir: base for the audit log. Usually `data/proactive/`.
        http_post: dependency-injected HTTP transport, default `httpx.post`.
            Tests pass a mock; production code passes None to use httpx.
        request_timeout: seconds before HTTP timeout. nanobanana can take
            ~10s to return so 60s gives generous headroom.

    Returns a ToolResult; check `.ok` to branch.
    """
    audit = ToolAuditEntry(
        phone_hash=dossier.phone_hash,
        tool="nanobanana",
        brief=brief,
    )

    # 1. Scrub. No-network code path if blocked.
    scrub = scrub_for_external_api(brief, dossier)
    if not scrub.ok:
        audit.scrubbed_ok = False
        audit.scrub_reason = scrub.reason()
        audit.api_status = "blocked"
        append_audit_entry(audit_base_dir, audit)
        return ToolResult(
            ok=False,
            tool="nanobanana",
            error=f"scrub_blocked: {scrub.reason()}",
            scrub_reason=scrub.reason(),
        )

    # 2. API call. Missing key is an explicit error, not a silent skip —
    # the agent should know it can't use this tool.
    if not api_key:
        audit.api_status = "error: nanobanana_api_key_missing"
        append_audit_entry(audit_base_dir, audit)
        return ToolResult(
            ok=False,
            tool="nanobanana",
            error="nanobanana_api_key_missing",
        )

    url = f"{endpoint.rstrip('/')}/{model}:generateContent?key={api_key}"
    payload: Dict[str, Any] = {
        "contents": [{"parts": [{"text": brief}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }

    post = http_post or httpx.post
    try:
        response = post(url, json=payload, timeout=request_timeout)
    except Exception as e:
        audit.api_status = f"error: {type(e).__name__}: {e}"
        append_audit_entry(audit_base_dir, audit)
        return ToolResult(
            ok=False,
            tool="nanobanana",
            error=f"http_error: {e}",
        )

    if response.status_code != 200:
        audit.api_status = f"error: http_{response.status_code}"
        append_audit_entry(audit_base_dir, audit)
        return ToolResult(
            ok=False,
            tool="nanobanana",
            error=f"api_status_{response.status_code}: {response.text[:200]}",
        )

    # 3. Extract the inline base64-encoded PNG from the response. The
    # Gemini API shape is documented at
    # https://ai.google.dev/gemini-api/docs/image-generation — the image
    # bytes live under candidates[0].content.parts[i].inline_data.data.
    try:
        body = response.json()
        parts = body["candidates"][0]["content"]["parts"]
        b64_data: Optional[str] = None
        for part in parts:
            if "inline_data" in part:
                b64_data = part["inline_data"].get("data")
                break
            if "inlineData" in part:  # alternate casing in some SDKs
                b64_data = part["inlineData"].get("data")
                break
        if b64_data is None:
            raise ValueError("no inline_data in any part")
    except Exception as e:
        audit.api_status = f"error: response_parse: {e}"
        append_audit_entry(audit_base_dir, audit)
        return ToolResult(
            ok=False,
            tool="nanobanana",
            error=f"response_parse_error: {e}",
        )

    # 4. Save the PNG. Filename includes timestamp so multiple gens for the
    # same user don't collide.
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
    artifact_path = artifacts_dir / f"{ts}_nanobanana.png"
    artifact_path.write_bytes(base64.b64decode(b64_data))

    audit.api_status = "ok"
    audit.artifact_path = str(artifact_path)
    append_audit_entry(audit_base_dir, audit)

    return ToolResult(
        ok=True,
        tool="nanobanana",
        artifact_path=artifact_path,
    )
