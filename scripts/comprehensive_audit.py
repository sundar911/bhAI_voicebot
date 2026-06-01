"""
Comprehensive accuracy audit of the dev bot.

Runs 17 multi-turn scenarios across 7 languages and 6 topic types through
the FULL v1.5 LLM stack — same Sonnet model, same Sonnet+context router,
same use-case blocks, same MEMORY_INSTRUCTION, same prompt version
(prompt_v1_pilot), language detection now enabled.

User messages are reconstructed for accuracy-test purposes (where
real-user turns from the audit corpus exist, they're used; otherwise
realistic constructions per audit-paraphrase conventions). Each
scenario uses a fresh ConversationStore so prior runs don't contaminate.

Skips STT/TTS (text in/out — doesn't affect reply content). Tagging
decisions, memory patches, escalation flags all printed for analysis.

Cost: ~$2-3 in Sonnet calls. Run with:
    uv run python scripts/comprehensive_audit.py 2>&1 | tee /tmp/audit_output.txt
"""

import os
import sys
from pathlib import Path
from typing import List, Tuple

from dotenv import load_dotenv

ROOT = Path("/Users/sundarraghavanl/PycharmProjects/bhAI_voice_bot")
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

os.environ.setdefault("PROMPT_VERSION", "prompt_v1_pilot")
os.environ.setdefault("LLM_BACKEND", "claude")
os.environ.setdefault("KB_ROUTER_ENABLED", "true")
os.environ.setdefault("KB_ROUTER_BACKEND", "llm")

from src.bhai.config import load_config  # noqa: E402
from src.bhai.llm import create_llm  # noqa: E402
from src.bhai.memory.store import ConversationStore  # noqa: E402
from src.bhai.memory.summarizer import merge_facts  # noqa: E402


def _apply_memory_patches(store, phone, prior_memory, memory_patches):
    if not memory_patches:
        return
    new_summary = memory_patches.get("summary")
    new_facts = memory_patches.get("facts") or []
    if not new_summary and not new_facts:
        return
    existing_summary = (prior_memory or {}).get("summary", "")
    existing_facts = (prior_memory or {}).get("facts", []) or []
    merged_summary = new_summary if new_summary else existing_summary
    merged_facts = (
        merge_facts(existing_facts, new_facts) if new_facts else existing_facts
    )
    store.save_memory(phone, merged_summary, merged_facts)


# Each scenario: (scenario_id, lang, topic_tags, turns)
# turns is a list of user messages; bot replies between them maintain
# conversation history.
SCENARIOS: List[Tuple[str, str, str, List[str]]] = [
    # ──────── HINDI ────────
    (
        "H1",
        "hindi",
        "companion + capabilities",
        [
            "नमस्ते भाई, कैसी हो?",
            "तुम क्या क्या कर सकती हो मेरे लिए?",
        ],
    ),
    (
        "H2",
        "hindi",
        "finance_advice (loan + medical debt cross-impact)",
        [
            "भाई, एक नया ₹1 lakh का loan लेना है saree business के लिए, ₹8000 EMI होगी। बेटी का accident हुआ था पिछले साल, hospital का कर्जा अभी भी है। फिर भी मुझे ये loan लेना है।",
            "हाँ, बस यही plan है, करना है मुझे।",
        ],
    ),
    (
        "H3",
        "hindi",
        "scheme_kb (PAN card for adult woman, tests instant e-PAN)",
        [
            "मेरी wife का PAN card बनवाना है, कैसे करूँ?",
        ],
    ),
    (
        "H4",
        "hindi",
        "scheme_kb (bank account, tests location-asking)",
        [
            "मेरी बेटी 18 की हो गई है, उसका bank account खोलना है। कौन से bank में जाऊँ?",
        ],
    ),
    # ──────── MARATHI ────────
    (
        "M1",
        "marathi",
        "companion + grievance",
        [
            "नमस्कार दादा, माझा supervisor मला रोज ओरडतो सगळ्यांच्या समोर. खूप त्रास होतोय.",
        ],
    ),
    (
        "M2",
        "marathi",
        "scheme_kb (Ladki Bahin eligibility — tests completeness)",
        [
            "ताई, माझ्या बहिणीला लाडकी बहीण योजना मिळेल का? ती 35 वर्षांची आहे, विधवा आहे.",
        ],
    ),
    # ──────── TAMIL ────────
    (
        "T1",
        "tamil",
        "scheme_kb (widowed sister — REGRESSION on eligibility-completeness)",
        [
            "எங்க அக்கா husband இறந்துட்டாங்க, வேலை இல்ல. அவங்களுக்கு Ladki Bahin Yojana கிடைக்குமா?",
        ],
    ),
    (
        "T2",
        "tamil",
        "scheme_kb (Borivali Setu Kendra — REGRESSION on no-fabrication + verification-pairing)",
        [
            "Borivali-ல Setu Kendra எங்க இருக்கு? என் அக்காவுக்கு Ladki Bahin apply பண்ணணும்.",
        ],
    ),
    (
        "T3",
        "tamil",
        "general knowledge (restaurant recommendation in Tamil)",
        [
            "Mumbai-ல BC area-ல வந்து family-க்கு வாரம் dinner எங்க போகலாம்? Budget 1500.",
        ],
    ),
    # ──────── TELUGU ────────
    (
        "Te1",
        "telugu",
        "scheme_kb (Ladki Bahin from Telugu speaker)",
        [
            "నేను Maharashtra-లో ఉంటున్నాను, నాకు Ladki Bahin Yojana దొరుకుతుందా? నాకు 30 ఏళ్లు, పెళ్లి అయింది.",
        ],
    ),
    (
        "Te2",
        "telugu",
        "companion + family stress",
        [
            "నమస్తే అన్నా, ఇంట్లో ఈ రోజు చాలా టెన్షన్‌గా ఉంది. పిల్లల ఫీజు కట్టాలి, చేతిలో పైసలు లేవు.",
        ],
    ),
    # ──────── MALAYALAM ────────
    (
        "Ml1",
        "malayalam",
        "finance_advice (loan in Malayalam)",
        [
            "ഏട്ടാ, എനിക്ക് ₹50,000 ലോൺ വേണം machine വാങ്ങാൻ. EMI ₹3,000. എടുക്കാമോ?",
        ],
    ),
    (
        "Ml2",
        "malayalam",
        "scheme_kb (Aadhaar address change in Malayalam)",
        [
            "എനിക്ക് Aadhaar-ൽ address മാറ്റണം. എങ്ങനെ ചെയ്യണം?",
        ],
    ),
    # ──────── BENGALI ────────
    (
        "B1",
        "bengali",
        "general knowledge (school recommendation in Bengali)",
        [
            "ভাই, আমার মেয়ের জন্য Mumbai-তে একটা ভালো English-medium government school suggest করো। Kafparade-এর কাছে।",
        ],
    ),
    (
        "B2",
        "bengali",
        "multi-topic (PAN + workplace grievance)",
        [
            "ভাই দুটো কথা — wife-এর PAN card বানাতে হবে। আর কাজে supervisor রোজ ঝামেলা করছে। কোনটা আগে করব?",
        ],
    ),
    # ──────── KANNADA ────────
    (
        "K1",
        "kannada",
        "companion + capabilities (in Kannada)",
        [
            "ನಮಸ್ಕಾರ ಅಣ್ಣ, ನೀವು ಯಾವ ಯಾವ ಭಾಷೆಗಳಲ್ಲಿ ಮಾತಾಡಬಲ್ಲಿರಿ?",
        ],
    ),
    (
        "K2",
        "kannada",
        "scheme_kb (PAN card in Kannada)",
        [
            "ನನಗೆ PAN card ಮಾಡಲು ಯಾವ documents ಬೇಕು? ಬೇಗ ಬೇಕು.",
        ],
    ),
]


def run_scenario(scenario_id, lang, topic_tags, turns, cfg, db_path):
    print()
    print("=" * 78)
    print(f"SCENARIO {scenario_id}  |  {lang.upper()}  |  {topic_tags}")
    print("=" * 78)

    if db_path.exists():
        db_path.unlink()
    store = ConversationStore(db_path)
    llm = create_llm(cfg)
    phone = f"tg_audit_{scenario_id}"
    session_id = f"audit_{scenario_id}"

    for i, user_text in enumerate(turns, 1):
        store.save_message(phone, "user", user_text, session_id)
        memory = store.get_memory(phone)
        memory_summary = memory["summary"] if memory else ""
        extracted_facts = "\n".join(f"- {f}" for f in memory["facts"]) if memory else ""
        recent = store.get_recent_messages(phone, limit=8)
        history_for_call = recent[:-1] if recent else []

        result = llm.generate_with_emotions(
            user_text,
            domain="hr_admin",
            user_profile="",
            memory_summary=memory_summary,
            extracted_facts=extracted_facts,
            conversation_history=history_for_call,
            is_new_session=(i == 1),
            mode_instruction="",
        )

        store.save_message(phone, "assistant", result["text"], session_id)
        _apply_memory_patches(store, phone, memory, result.get("memory_patches"))

        print(f"\n--- Turn {i} ---")
        print(f"USER:  {user_text}")
        print(f"BOT:   {result['text']}")
        patches = result.get("memory_patches")
        if patches:
            if patches.get("summary"):
                print(f"  [memory] summary: {patches['summary'][:200]}")
            for f in patches.get("facts") or []:
                print(f"  [memory] fact: {f}")
        if result.get("escalate"):
            print(f"  [escalate] true  (category={result.get('category')})")

    store.close()


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("FATAL: ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 1
    cfg = load_config()
    tmp_db = Path("/tmp/bhai_audit.db")
    if tmp_db.exists():
        tmp_db.unlink()
    for sc in SCENARIOS:
        run_scenario(*sc, cfg=cfg, db_path=tmp_db)
    if tmp_db.exists():
        tmp_db.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
