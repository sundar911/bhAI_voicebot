"""Google Programmable Search wrapper for the proactive agent.

Uses Google's Custom Search JSON API — separate API key (config
`google_search_api_key`) and a Custom Search Engine ID (`google_search_cse_id`)
created once in the Google Cloud Console. If either is missing the wrapper
returns a clean "not configured" error rather than failing the agent loop.

Hard contract: every query passes through the privacy scrub layer before
any network egress. The scrubbed query — never raw user PII — goes to
Google. Every call writes one audit row regardless of outcome.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import httpx

from ..dossier_loader import UserDossier
from ..scrubbers import scrub_for_external_api
from ._audit_log import ToolAuditEntry, append_audit_entry
from ._types import ToolResult

logger = logging.getLogger("bhai.proactive.web_search")

# httpx.get signature for dependency injection in tests.
HttpGetFn = Callable[..., httpx.Response]


def search(
    query: str,
    dossier: UserDossier,
    *,
    api_key: str,
    cse_id: str,
    audit_base_dir: Path,
    max_results: int = 5,
    endpoint: str = "https://customsearch.googleapis.com/customsearch/v1",
    http_get: Optional[HttpGetFn] = None,
    request_timeout: float = 15.0,
) -> ToolResult:
    """Search Google for `query` on behalf of the user described by `dossier`.

    Args:
        query: search query string. MUST be scrub-safe — caller is responsible
            for not embedding user PII in the query phrasing. We re-scrub here
            as defense-in-depth.
        dossier: the user's dossier — needed so the scrub layer knows which
            name(s) to block.
        api_key: Google Search API key (config.google_search_api_key).
        cse_id: Programmable Search Engine ID (config.google_search_cse_id).
        audit_base_dir: usually `data/proactive/`.
        max_results: number of results to request (Google caps at 10 per call).
        endpoint: API URL (defaulted; configurable for testing).
        http_get: dependency-injected HTTP transport, default `httpx.get`.
        request_timeout: seconds before HTTP timeout.

    Returns ToolResult with `payload` set to a list of
    `{"title", "link", "snippet"}` dicts on success.
    """
    audit = ToolAuditEntry(
        phone_hash=dossier.phone_hash,
        tool="web_search",
        brief=query,
    )

    # 1. Scrub — no network if blocked.
    scrub = scrub_for_external_api(query, dossier)
    if not scrub.ok:
        audit.scrubbed_ok = False
        audit.scrub_reason = scrub.reason()
        audit.api_status = "blocked"
        append_audit_entry(audit_base_dir, audit)
        return ToolResult(
            ok=False,
            tool="web_search",
            error=f"scrub_blocked: {scrub.reason()}",
            scrub_reason=scrub.reason(),
        )

    # 2. Config check. Both keys must be present.
    if not api_key:
        audit.api_status = "error: google_search_api_key_missing"
        append_audit_entry(audit_base_dir, audit)
        return ToolResult(
            ok=False, tool="web_search", error="google_search_api_key_missing"
        )
    if not cse_id:
        audit.api_status = "error: google_search_cse_id_missing"
        append_audit_entry(audit_base_dir, audit)
        return ToolResult(
            ok=False, tool="web_search", error="google_search_cse_id_missing"
        )

    # 3. API call.
    params: Dict[str, Union[str, int]] = {
        "key": api_key,
        "cx": cse_id,
        "q": query,
        "num": min(max(max_results, 1), 10),  # Google caps at 10
    }
    get = http_get or httpx.get
    try:
        response = get(endpoint, params=params, timeout=request_timeout)
    except Exception as e:
        audit.api_status = f"error: {type(e).__name__}: {e}"
        append_audit_entry(audit_base_dir, audit)
        return ToolResult(ok=False, tool="web_search", error=f"http_error: {e}")

    if response.status_code != 200:
        audit.api_status = f"error: http_{response.status_code}"
        append_audit_entry(audit_base_dir, audit)
        return ToolResult(
            ok=False,
            tool="web_search",
            error=f"api_status_{response.status_code}: {response.text[:200]}",
        )

    # 4. Parse — extract just title/link/snippet for each item.
    try:
        body = response.json()
        items: List[Dict[str, str]] = []
        for item in body.get("items", []):
            items.append(
                {
                    "title": item.get("title", ""),
                    "link": item.get("link", ""),
                    "snippet": item.get("snippet", ""),
                }
            )
    except Exception as e:
        audit.api_status = f"error: response_parse: {e}"
        append_audit_entry(audit_base_dir, audit)
        return ToolResult(
            ok=False, tool="web_search", error=f"response_parse_error: {e}"
        )

    audit.api_status = "ok"
    audit.extra = {"result_count": len(items)}
    append_audit_entry(audit_base_dir, audit)

    return ToolResult(ok=True, tool="web_search", payload=items)
