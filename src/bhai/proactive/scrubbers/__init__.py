"""Privacy scrub layer for external tool calls (step 3 of the v2 proactive
build — see tmp/v2_proactive_design.md §3).

The proactive agent will call external APIs (nanobanana for image gen, web
search) on behalf of users. CLAUDE.md is binding: religion, caste,
disability, and loan info are never sent to any external API. Beyond that
hard rule, no user PII (name, phone, location like BC/MIDC, community
names like Aarey/Pardhi, impact-team staff names) may leak either.

This scrub layer is enforced in code, not in prompts. Prompt-based privacy
is unreliable; code-based scrubbing is unconditional. Every external tool
wrapper (step 4) must call through `scrub_for_external_api()` before any
network egress.
"""

from .combined import ScrubResult, scrub_for_external_api
from .content import ContentScrubResult, scrub_content
from .pii import PiiScrubResult, extract_name_terms, scrub_pii

__all__ = [
    "ScrubResult",
    "scrub_for_external_api",
    "PiiScrubResult",
    "extract_name_terms",
    "scrub_pii",
    "ContentScrubResult",
    "scrub_content",
]
