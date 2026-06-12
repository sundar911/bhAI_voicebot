"""One-shot smoke test for the nanobanana wrapper against the real Gemini API.

Validates the request shape we guessed at in src/bhai/proactive/tools/nanobanana.py
without burning more than one image's worth of quota. Writes the PNG (if it
works) to tmp/smoke_nanobanana_<ts>.png and prints what happened.

Usage: uv run python scripts/smoke_test_nanobanana.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

# Load .env so NANOBANANA_API_KEY / GEMINI_API_KEY / GOOGLE_GENAI_API_KEY
# are picked up regardless of which name Sundar used.
load_dotenv()

from src.bhai.config import load_config  # noqa: E402
from src.bhai.proactive.dossier_loader import UserDossier  # noqa: E402
from src.bhai.proactive.tools.nanobanana import generate_image  # noqa: E402


def main() -> int:
    cfg = load_config()
    if not cfg.nanobanana_api_key:
        print(
            "ERROR: no API key found. Set one of "
            "NANOBANANA_API_KEY / GEMINI_API_KEY / GOOGLE_GENAI_API_KEY in .env"
        )
        return 1

    # Synthetic dossier — no real user, so scrub layer can't accidentally
    # over-block. Brief is the canonical safe Manimala saree logo from the
    # kickoff (no names, no locations, no PII).
    dossier = UserDossier(
        phone="smoke_test",
        phone_hash="smoke" + "0" * 7,
        summary="",
        core_facts=[],
    )
    brief = (
        "Logo for a saree wholesaler who sells via WhatsApp groups to "
        "10-15 regular customers. Target audience: mid-income women "
        "aged 30-50 buying for festivals and weddings. Warm earthy "
        "palette, traditional motifs, minimalist. Square format."
    )

    artifacts_dir = ROOT / "tmp" / "smoke_nanobanana"
    audit_dir = ROOT / "tmp" / "smoke_audit"

    print(f"Model:    {cfg.nanobanana_model}")
    print(f"Endpoint: {cfg.nanobanana_endpoint}")
    print(f"Brief:    {brief[:80]}...")
    print()
    print("Calling Gemini image gen — this can take ~10s...")
    print()

    result = generate_image(
        brief=brief,
        dossier=dossier,
        api_key=cfg.nanobanana_api_key,
        model=cfg.nanobanana_model,
        endpoint=cfg.nanobanana_endpoint,
        artifacts_dir=artifacts_dir,
        audit_base_dir=audit_dir,
    )

    if result.ok:
        print(f"✓ SUCCESS — image saved to {result.artifact_path}")
        if result.artifact_path is not None:
            print(f"  size: {result.artifact_path.stat().st_size} bytes")
        return 0

    print(f"✗ FAILED — {result.error}")
    if result.scrub_reason:
        print(f"  scrub: {result.scrub_reason}")
    print()
    print(f"Audit log:  {audit_dir}/{dossier.phone_hash}/tool_audit.jsonl")
    return 2


if __name__ == "__main__":
    sys.exit(main())
