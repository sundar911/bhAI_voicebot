"""
One-off validation: send real + synthetic transcripts through LLMKBRouter
(Sonnet 4.6) and print its decisions. Used to sanity-check the two-line
output format (KB + USE_CASES) against actual pilot inputs before
relying on it in production.

Run: uv run python scripts/validate_llm_router.py
"""

import os
import sqlite3
import sys
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import load_dotenv

# Add repo root for imports
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.bhai.llm.kb_router import KBRouter  # noqa: E402
from src.bhai.llm.llm_router import LLMKBRouter  # noqa: E402

load_dotenv()

KB_DIR = ROOT / "knowledge_base"
DB_PATH = ROOT / "data" / "conversations.db"


# Synthetic transcripts covering every use-case bucket so we can verify
# tagging behaviour even if the live DB has none of a kind.
SYNTHETIC: list[tuple[str, str, set[str]]] = [
    # (transcript, expected_tag_hint, allowed_tags)
    # Companion / chitchat — should emit no use-cases
    ("नमस्ते भाई, कैसी हो?", "companion (no tag)", set()),
    ("आज मन भारी है, कुछ अच्छा नहीं लग रहा।", "companion (no tag)", set()),
    # Scheme / docs — should emit scheme_kb (+ KB hit)
    ("राशन कार्ड के लिए क्या क्या डॉक्यूमेंट्स चाहिए?", "scheme_kb", {"scheme_kb"}),
    ("Aadhaar में नाम change कैसे करूँ?", "scheme_kb", {"scheme_kb"}),
    # Finance — should emit finance
    ("मेरा PF balance कितना है इस महीने?", "finance", {"finance"}),
    ("Salary slip मिली नहीं अभी तक, account में आ गई क्या?", "finance", {"finance"}),
    ("Loan की कितनी EMI बाकी है मेरी?", "finance", {"finance"}),
    # Grievance — should emit grievance
    (
        "Supervisor मुझे रोज़ डांटती है, समझ नहीं आ रहा क्या करूँ।",
        "grievance",
        {"grievance"},
    ),
    ("Co-worker harass कर रहा है, बहुत परेशान हूँ।", "grievance", {"grievance"}),
    # Multi-label: grievance + finance (the modal "delayed salary" complaint)
    (
        "इस महीने salary नहीं आई, supervisor से पूछा तो कुछ बता ही नहीं रहे।",
        "grievance + finance",
        {"grievance", "finance"},
    ),
    # General knowledge — should emit general
    (
        "BC के पास ₹700 में 4 लोगों के लिए कोई बढ़िया Chinese restaurant बताओ।",
        "general",
        {"general"},
    ),
    (
        "बेटे के लिए karate classes Grant Road के पास कहाँ मिलेंगी?",
        "general",
        {"general"},
    ),
    ("मेरे बच्चे को पढ़ाई में मदद कैसे करूँ, कुछ tips दो।", "general", {"general"}),
]


def _load_real_transcripts(n: int = 12) -> list[str]:
    """Pull a handful of recent real user transcripts from the local DB."""
    if not DB_PATH.exists():
        print("(no local data/conversations.db — skipping real-transcript pull)")
        return []
    key = os.environ.get("BHAI_ENCRYPTION_KEY")
    if not key:
        print("(no BHAI_ENCRYPTION_KEY — skipping real-transcript pull)")
        return []
    f = Fernet(key.encode() if isinstance(key, str) else key)
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        "SELECT content_enc FROM messages WHERE role='user' "
        "ORDER BY timestamp DESC LIMIT 200"
    ).fetchall()
    seen: set[str] = set()
    out: list[str] = []
    for (enc,) in rows:
        try:
            msg = f.decrypt(enc.encode() if isinstance(enc, str) else enc).decode()
        except Exception:
            continue
        # Skip junk + dupes
        msg = msg.strip()
        if len(msg) < 8 or len(msg) > 220:
            continue
        norm = msg.lower()
        if norm in seen:
            continue
        seen.add(norm)
        # Skip obvious test pings
        if msg.lower().startswith(("testing", "hello", "hi ", "हेलो", "test ")):
            continue
        out.append(msg)
        if len(out) >= n:
            break
    return out


def main() -> int:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("FATAL: ANTHROPIC_API_KEY not set (check .env)")
        return 1

    fallback = KBRouter(KB_DIR / "helpdesk")
    router = LLMKBRouter(kb_dir=KB_DIR, fallback=fallback, api_key=api_key)

    fail_count = 0
    pass_count = 0

    print("\n=== SYNTHETIC (with expected tags) ===\n")
    for transcript, hint, expected in SYNTHETIC:
        result = router.route(transcript)
        kb_stems = [p.stem for p in result.paths if p.stem != "_index"]
        got = set(result.use_cases)
        match = got == expected
        if match:
            pass_count += 1
            marker = "✓"
        else:
            fail_count += 1
            marker = "✗"
        print(
            f"{marker} expected={sorted(expected) or '∅'}  got={sorted(got) or '∅'}  kb={kb_stems}"
        )
        print(f"   hint={hint}")
        print(f"   in  : {transcript}")
        print()

    print(f"\n=== SYNTHETIC: {pass_count} match / {fail_count} mismatch ===\n")

    real = _load_real_transcripts(12)
    if real:
        print(
            f"\n=== REAL ({len(real)} from local DB, no ground-truth — eyeball them) ===\n"
        )
        for transcript in real:
            result = router.route(transcript)
            kb_stems = [p.stem for p in result.paths if p.stem != "_index"]
            tags = result.use_cases or ["∅ (companion)"]
            print(f"   tags={tags}  kb={kb_stems}")
            print(f"   in  : {transcript}")
            print()

    return 1 if fail_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
