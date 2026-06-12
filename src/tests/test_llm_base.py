"""
Tests for src/bhai/llm/base.py — pure helper methods on BaseLLM.

We test via a minimal stub subclass so we can instantiate BaseLLM
without a real API key or network call.
"""

import pytest

from bhai.config import load_config
from bhai.llm.base import BaseLLM


class StubLLM(BaseLLM):
    """Concrete subclass of BaseLLM that returns a fixed response."""

    model_name = "stub-model"

    def _call_api(self, system_prompt: str, user_message: str) -> str:
        return "सब ठीक है।\nESCALATE: false"


@pytest.fixture
def stub_llm(tmp_knowledge_base):
    cfg = load_config()
    return StubLLM(cfg, knowledge_base_dir=tmp_knowledge_base)


# ── _build_user_message ────────────────────────────────────────────────


def test_build_user_message_simple():
    """With no history, message contains the transcript."""
    msg = BaseLLM._build_user_message("salary kab aayegi?")
    assert "salary kab aayegi?" in msg


def test_build_user_message_with_history():
    """Conversation history appears above the transcript."""
    history = [
        {"role": "user", "content": "PF ke baare mein baat karo"},
        {"role": "assistant", "content": "PF ke liye HR se form lo"},
    ]
    msg = BaseLLM._build_user_message("salary?", conversation_history=history)
    assert "User: PF ke baare mein baat karo" in msg
    assert "भाई: PF ke liye HR se form lo" in msg
    assert "salary?" in msg


def test_build_user_message_new_session_flag():
    """is_new_session=True adds a new-session notice."""
    msg = BaseLLM._build_user_message("hello", is_new_session=True)
    assert "नई बातचीत" in msg or "Nayi conversation" in msg


# ── _detect_escalation ────────────────────────────────────────────────


def test_detect_escalation_true():
    assert BaseLLM._detect_escalation("Kuch nahi pata.\nESCALATE: true") is True


def test_detect_escalation_false():
    assert (
        BaseLLM._detect_escalation("Salary 5th ko aati hai.\nESCALATE: false") is False
    )


def test_detect_escalation_case_insensitive():
    assert BaseLLM._detect_escalation("Escalate: TRUE") is True


def test_detect_escalation_fallback_on_bare_word():
    """If 'escalate' appears without the colon pattern, still returns True."""
    assert BaseLLM._detect_escalation("please escalate this immediately") is True


def test_detect_escalation_absent_returns_false():
    assert BaseLLM._detect_escalation("Salary 5th ko aati hai.") is False


# ── _clean_response ───────────────────────────────────────────────────


def test_clean_response_removes_escalate_line():
    raw = "Salary 5th ko aati hai.\nESCALATE: false"
    cleaned = BaseLLM._clean_response(raw)
    assert "ESCALATE" not in cleaned
    assert "Salary 5th ko aati hai." in cleaned


def test_clean_response_strips_emotions_when_flag_set():
    raw = (
        "Sab theek hai.\n"
        "ESCALATE: false\n"
        'EMOTIONS_JSON: [{"text": "Sab theek hai.", "emotion": "neutral"}]'
    )
    cleaned = BaseLLM._clean_response(raw, strip_emotions=True)
    assert "EMOTIONS_JSON" not in cleaned
    assert "ESCALATE" not in cleaned
    assert "Sab theek hai." in cleaned


def test_clean_response_keeps_emotions_by_default():
    raw = "Answer.\nESCALATE: false\nEMOTIONS_JSON: []"
    cleaned = BaseLLM._clean_response(raw, strip_emotions=False)
    assert "EMOTIONS_JSON" in cleaned


# ── _strip_reasoning_leak ────────────────────────────────────────────


def test_strip_reasoning_leak_drops_system_prompt_paragraph():
    """Paragraphs mentioning 'system prompt' are leaked reasoning — strip them."""
    raw = (
        "User Malayalam में बोल रही हैं. system prompt कहता है Devanagari में जवाब दो.\n\n"
        "मणिमाला, नमस्ते! कैसी हैं आप?"
    )
    cleaned = BaseLLM._strip_reasoning_leak(raw)
    assert "system prompt" not in cleaned
    assert "मणिमाला, नमस्ते" in cleaned


def test_strip_reasoning_leak_drops_kb_jargon_paragraph():
    """The 2026-05-27 dev test caught bhAI saying 'मेरे KB में... detail नहीं है'.
    The KB family was added to the leak markers as a backstop; the
    architectural-jargon paragraph should now be dropped, leaving the
    actual useful general-knowledge paragraph."""
    raw = (
        "Scholarship की बात — मेरे KB में college scholarship का "
        "specific detail नहीं है, तो मैं वहाँ से पक्की जानकारी नहीं दे सकती।\n\n"
        "Maharashtra में government colleges की fees 5,000 से 15,000 रुपए "
        "के around होती है। National scholarship portal scholarships.gov.in पर देखो।"
    )
    cleaned = BaseLLM._strip_reasoning_leak(raw)
    assert "मेरे KB" not in cleaned
    assert "Maharashtra में government colleges" in cleaned
    assert "scholarships.gov.in" in cleaned


def test_strip_reasoning_leak_drops_knowledge_base_english():
    """The English form 'knowledge base' is also a markered leak."""
    raw = (
        "My knowledge base doesn't have this specific info.\n\n"
        "But here's what I know: ये एक अच्छा scheme है।"
    )
    cleaned = BaseLLM._strip_reasoning_leak(raw)
    assert "knowledge base" not in cleaned.lower()
    assert "अच्छा scheme है" in cleaned


def test_strip_reasoning_leak_drops_anti_sycophancy_marker():
    """References to internal prompt rules ('anti-sycophancy') are reasoning leakage."""
    raw = (
        "यह loan के बारे में है. Anti-sycophancy rule apply होता है, मुझे numbers पूछने हैं.\n\n"
        "₹50,000 का loan — एक बात बताइए, अभी कितना EMI जा रहा है?"
    )
    cleaned = BaseLLM._strip_reasoning_leak(raw)
    assert "anti-sycophancy" not in cleaned.lower()
    assert "₹50,000 का loan" in cleaned


def test_strip_reasoning_leak_preserves_clean_response():
    """A normal response with no reasoning markers passes through untouched."""
    raw = "अरे मणिमाला, कैसी हैं आप? आज खाने में क्या बनाया?"
    cleaned = BaseLLM._strip_reasoning_leak(raw)
    assert cleaned == raw


def test_strip_reasoning_leak_falls_back_to_last_paragraph():
    """If every paragraph contains a marker, keep the last as fallback."""
    raw = (
        "system prompt कहता है X.\n\n"
        "anti-sycophancy rule apply होता है इसलिए मुझे Y करना है."
    )
    cleaned = BaseLLM._strip_reasoning_leak(raw)
    # Last paragraph kept even though it also has a marker — better than empty.
    assert cleaned != ""
    assert "anti-sycophancy" in cleaned.lower()


def test_clean_response_strips_reasoning_leak_end_to_end():
    """The full clean pipeline strips leakage (the Manimala May 11 case)."""
    raw = (
        "User Malayalam में बोल रही हैं. system prompt कहता है Devanagari Hindi में जवाब दो TTS के लिए.\n\n"
        "यह एक financial decision है. Anti-sycophancy rule apply होता है. मुझे पहले पूरा हिसाब समझना है.\n\n"
        "मणिमाला, ₹50,000 लोन — एक बात बताइए, अभी हर महीने कितना खर्च होता है?"
    )
    cleaned = BaseLLM._clean_response(raw)
    assert "system prompt" not in cleaned
    assert "anti-sycophancy" not in cleaned.lower()
    assert "मणिमाला, ₹50,000 लोन" in cleaned


# ── _strip_markdown ───────────────────────────────────────────────────


def test_strip_markdown_removes_bold_asterisks():
    """**bold** → bold (TTS reads ** literally as 'asterisk asterisk')."""
    assert BaseLLM._strip_markdown("**Sukanya Samriddhi**") == "Sukanya Samriddhi"


def test_strip_markdown_removes_leading_dash_bullet():
    """A line starting with '- ' becomes the text without the bullet."""
    assert BaseLLM._strip_markdown("- पहली बात") == "पहली बात"


def test_strip_markdown_removes_leading_asterisk_bullet():
    assert BaseLLM._strip_markdown("* दूसरी बात") == "दूसरी बात"


def test_strip_markdown_removes_numbered_list_marker():
    assert BaseLLM._strip_markdown("1. पहली बात") == "पहली बात"


def test_strip_markdown_removes_heading():
    assert BaseLLM._strip_markdown("## Schemes") == "Schemes"


def test_strip_markdown_removes_backticks():
    assert BaseLLM._strip_markdown("call `office`") == "call office"


def test_strip_markdown_leaves_plain_hindi_unchanged():
    text = "नमस्ते भाई, सब ठीक है ना?"
    assert BaseLLM._strip_markdown(text) == text


def test_strip_markdown_handles_empty_string():
    assert BaseLLM._strip_markdown("") == ""


def test_strip_markdown_preserves_mid_sentence_dash():
    """Dashes inside a sentence shouldn't be stripped — only leading bullets."""
    text = "दोनों बेटियों के लिए — दो योजनाएँ हैं"
    assert BaseLLM._strip_markdown(text) == text


# Phone-number extraction is owned by the webhook
# (inference/webhooks/telegram_webhook._extract_phone_numbers) — it's been
# wired since 2026-04-28 (commit 48b6233c). Tests for that flow live in
# test_telegram_webhook.py.


# ── _strip_emoji ──────────────────────────────────────────────────────


def test_strip_emoji_removes_common_emojis():
    """Folded-hands, smileys, check marks all get scrubbed before TTS sees them."""
    assert BaseLLM._strip_emoji("Namaste 🙏 Manimala ji!") == "Namaste Manimala ji!"
    assert BaseLLM._strip_emoji("😄😄😄 Sab theek hai") == "Sab theek hai"
    assert BaseLLM._strip_emoji("Done ✅") == "Done"


def test_strip_emoji_preserves_devanagari():
    """Indic codepoints live below U+0E00 — they must NOT be touched."""
    text = "अरे, सब ठीक है ना? बेटी कैसी है?"
    assert BaseLLM._strip_emoji(text) == text


def test_strip_emoji_preserves_tamil_and_gujarati():
    """The exact prod-bug case: Tamil nudges with 🙏 had the emoji leak but
    the Tamil text must stay intact end-to-end."""
    assert BaseLLM._strip_emoji("மணிமாலா ஜி") == "மணிமாலா ஜி"
    assert BaseLLM._strip_emoji("બહાર ગઈ") == "બહાર ગઈ"
    # The canonical Manimala prod-bug nudge: same Tamil text, emoji gone.
    assert (
        BaseLLM._strip_emoji("மணிமாலா, காலை வணக்கம்! 🙏 இன்னைக்கு easy-ஆ இருக்கா?")
        == "மணிமாலா, காலை வணக்கம்! இன்னைக்கு easy-ஆ இருக்கா?"
    )


def test_strip_emoji_handles_empty_string():
    assert BaseLLM._strip_emoji("") == ""


def test_strip_emoji_collapses_double_spaces_from_removed_emojis():
    """Mid-sentence emoji removal leaves 'word  word' — collapse to one space."""
    assert BaseLLM._strip_emoji("Hi 😊 there") == "Hi there"


def test_strip_emoji_handles_zwj_sequences():
    """ZWJ-joined family emojis are stripped cleanly (ZWJ U+200D is in the pattern)."""
    # Family man+woman+boy: U+1F468 U+200D U+1F469 U+200D U+1F466
    assert BaseLLM._strip_emoji("Bachche 👨‍👩‍👦 ke saath") == "Bachche ke saath"


def test_strip_emoji_strips_dingbats_and_misc_symbols():
    """Sun, snowflake, sparkle, checkmark — all in misc-symbols / dingbats."""
    assert BaseLLM._strip_emoji("Aaj ☀ achha din") == "Aaj achha din"
    assert BaseLLM._strip_emoji("Done ✔") == "Done"
    assert BaseLLM._strip_emoji("Magic ✨") == "Magic"


# ── _parse_emotion_segments ───────────────────────────────────────────


def test_parse_emotion_segments_valid():
    raw = (
        "Salary 5th ko aayegi.\n"
        'EMOTIONS_JSON: [{"text": "Salary 5th ko aayegi.", "emotion": "neutral"}]'
    )
    segments = BaseLLM._parse_emotion_segments(raw)
    assert segments is not None
    assert len(segments) == 1
    assert segments[0]["text"] == "Salary 5th ko aayegi."
    assert segments[0]["emotion"] == "neutral"


def test_parse_emotion_segments_no_json_line():
    assert BaseLLM._parse_emotion_segments("Just a normal response.") is None


def test_parse_emotion_segments_invalid_json():
    raw = "Answer.\nEMOTIONS_JSON: not valid json {"
    assert BaseLLM._parse_emotion_segments(raw) is None


def test_parse_emotion_segments_missing_text_key():
    """Segments without 'text' key are rejected."""
    raw = 'EMOTIONS_JSON: [{"emotion": "neutral"}]'
    assert BaseLLM._parse_emotion_segments(raw) is None


# ── _build_system_prompt ──────────────────────────────────────────────


def test_system_prompt_loads_from_version(stub_llm):
    """System prompt loads from prompts/{version}.md and mentions भाई."""
    prompt = stub_llm._build_system_prompt("hr_admin")
    assert len(prompt) > 500  # non-trivial prompt content
    assert "भाई" in prompt or "BHAI" in prompt


def test_system_prompt_includes_user_profile(stub_llm):
    prompt = stub_llm._build_system_prompt(
        "hr_admin", user_profile="Yashoda, works night shift."
    )
    assert "Yashoda" in prompt


def test_system_prompt_includes_memory_summary(stub_llm):
    prompt = stub_llm._build_system_prompt(
        "hr_admin", memory_summary="User asked about PF twice."
    )
    assert "PF" in prompt


# ── _detect_outreach_claim ─────────────────────────────────────────────


def test_detect_outreach_claim_clean_response_returns_none():
    """A normal helpful response with no outreach claim is fine."""
    text = "आज खाने में क्या बनाया है? मुझे curry बहुत पसंद है।"
    assert BaseLLM._detect_outreach_claim(text, escalate=False) is None


def test_detect_outreach_claim_past_tense_vijay_attribution():
    """'Vijay ने बताया' is a fake-attribution lie, always."""
    text = "Vijay ने बताया कि Grant Road पर karate classes हैं।"
    assert BaseLLM._detect_outreach_claim(text, escalate=False) is not None


def test_detect_outreach_claim_past_tense_self_action():
    """'मैंने ... पूछ लिया' is a past-tense outreach lie, always."""
    text = "मैंने Vijay से karate के बारे में पूछ लिया है।"
    assert BaseLLM._detect_outreach_claim(text, escalate=False) is not None


def test_detect_outreach_claim_past_tense_blocked_even_with_escalate():
    """Past-tense outreach is a lie even when ESCALATE: true (you can't
    have already messaged anyone in the same turn)."""
    text = "Vijay ने बताया कि classes Grant Road पर हैं।"
    assert BaseLLM._detect_outreach_claim(text, escalate=True) is not None


def test_detect_outreach_claim_future_tense_without_escalate_flagged():
    """'मैं Vijay से पूछूँगी' without ESCALATE: true is a lie — bhAI cannot
    actually message Vijay."""
    text = "अच्छा, मैं Vijay से पूछ के बताऊँगी।"
    assert BaseLLM._detect_outreach_claim(text, escalate=False) is not None


def test_detect_outreach_claim_future_tense_with_escalate_allowed():
    """Future-tense outreach IS allowed when ESCALATE: true — the consent-
    gated flow does send a real email."""
    text = "Main team ko email kar rahi hoon — Rishi aur Sarfaraz ko."
    assert BaseLLM._detect_outreach_claim(text, escalate=True) is None


def test_detect_outreach_claim_negation_suppresses_match():
    """An honest disclaimer like 'मैं Vijay को message नहीं कर सकती'
    must not be flagged — the negation is the whole point."""
    text = "मैं अभी directly Vijay को message नहीं कर सकती — ये feature आ रहा है जल्दी।"
    assert BaseLLM._detect_outreach_claim(text, escalate=False) is None


def test_detect_outreach_claim_kb_check_phrase_allowed():
    """'मैं देख के बताती हूँ' (checking KB, not asking a human) is allowed."""
    text = "एक minute रुको, मैं देख के बताती हूँ — Aadhaar के documents क्या लगते हैं।"
    assert BaseLLM._detect_outreach_claim(text, escalate=False) is None


def test_detect_outreach_claim_text_in_send_phrase_allowed():
    """Sending a phone number via text (the system handles this) is NOT
    outreach — the regex must not trip on 'मैं number text में भेज रही हूँ'."""
    text = "Vijay का number मैं अभी text में भेज रही हूँ।"
    assert BaseLLM._detect_outreach_claim(text, escalate=False) is None


def test_detect_outreach_claim_empty_text_returns_none():
    assert BaseLLM._detect_outreach_claim("", escalate=False) is None
    assert BaseLLM._detect_outreach_claim("", escalate=True) is None


def test_detect_outreach_claim_jawab_aaya_flagged():
    """'Vijay का जवाब आया' (claiming a reply came) is a past-tense lie."""
    text = "Vijay का जवाब आया — कहते हैं Grant Road पर classes हैं।"
    assert BaseLLM._detect_outreach_claim(text, escalate=False) is not None


# ── _strip_memory_patches + _parse_memory_patches ────────────────────


def test_strip_memory_patches_removes_single_block():
    """A lone <memory> block is removed; surrounding text survives."""
    raw = "बहुत अच्छा, पता है। <memory>fact: name: Priya</memory> बच्ची की उम्र?"
    cleaned = BaseLLM._strip_memory_patches(raw)
    assert "<memory>" not in cleaned
    assert "fact:" not in cleaned
    assert "बहुत अच्छा" in cleaned
    assert "बच्ची की उम्र?" in cleaned


def test_strip_memory_patches_removes_multiple_blocks():
    raw = (
        "जवाब। <memory>fact: a</memory> और कुछ। <memory>fact: b</memory> "
        "<memory>summary: नया summary।</memory>"
    )
    cleaned = BaseLLM._strip_memory_patches(raw)
    assert "<memory>" not in cleaned
    assert "summary:" not in cleaned
    assert "जवाब।" in cleaned


def test_strip_memory_patches_handles_multiline_summary():
    """summary: patches can span multiple lines (DOTALL)."""
    raw = (
        "हाँ। <memory>summary: line one\nline two\nline three</memory>\n" "और कुछ बात?"
    )
    cleaned = BaseLLM._strip_memory_patches(raw)
    assert "<memory>" not in cleaned
    assert "line one" not in cleaned
    assert "line two" not in cleaned
    assert "और कुछ बात?" in cleaned


def test_strip_memory_patches_idempotent_on_clean_text():
    raw = "नमस्ते, सब ठीक है ना?"
    assert BaseLLM._strip_memory_patches(raw) == raw


def test_strip_memory_patches_case_insensitive_tag():
    raw = "ओके <MEMORY>fact: x</MEMORY> done."
    cleaned = BaseLLM._strip_memory_patches(raw)
    assert "<MEMORY>" not in cleaned and "<memory>" not in cleaned


def test_parse_memory_patches_returns_none_when_absent():
    assert BaseLLM._parse_memory_patches("just a normal reply") is None


def test_parse_memory_patches_extracts_facts():
    raw = (
        "Reply. <memory>fact: name: Priya</memory> "
        "<memory>fact: work_location: MIDC</memory>"
    )
    patches = BaseLLM._parse_memory_patches(raw)
    assert patches is not None
    assert patches["facts"] == ["name: Priya", "work_location: MIDC"]
    assert patches["summary"] is None


def test_parse_memory_patches_extracts_summary():
    raw = "Reply. <memory>summary: Priya MIDC में काम करती है। 2 बच्चे।</memory>"
    patches = BaseLLM._parse_memory_patches(raw)
    assert patches is not None
    assert patches["facts"] == []
    assert patches["summary"] == "Priya MIDC में काम करती है। 2 बच्चे।"


def test_parse_memory_patches_later_summary_wins():
    """If the model emits multiple summaries, last one is kept."""
    raw = (
        "<memory>summary: old summary</memory> "
        "<memory>fact: A</memory> "
        "<memory>summary: new summary</memory>"
    )
    patches = BaseLLM._parse_memory_patches(raw)
    assert patches is not None
    assert patches["summary"] == "new summary"
    assert patches["facts"] == ["A"]


def test_parse_memory_patches_ignores_unknown_ops():
    """A block without a recognised op prefix is logged + skipped, not raised."""
    raw = "<memory>delete: foo</memory> " "<memory>fact: real one</memory>"
    patches = BaseLLM._parse_memory_patches(raw)
    assert patches is not None
    assert patches["facts"] == ["real one"]


def test_parse_memory_patches_empty_body_ignored():
    raw = "<memory></memory> <memory>fact: real</memory>"
    patches = BaseLLM._parse_memory_patches(raw)
    assert patches is not None
    assert patches["facts"] == ["real"]


def test_clean_response_strips_memory_blocks_end_to_end():
    """Full clean pipeline strips memory, ESCALATE, and markdown together."""
    raw = (
        "नमस्ते Priya, अच्छा लगा सुनके।\n"
        "<memory>fact: name: Priya</memory>\n"
        "<memory>fact: work_location: MIDC</memory>\n"
        "ESCALATE: false"
    )
    cleaned = BaseLLM._clean_response(raw)
    assert "<memory>" not in cleaned
    assert "fact:" not in cleaned
    assert "ESCALATE" not in cleaned
    assert "नमस्ते Priya" in cleaned


# ── use-case block injection ──────────────────────────────────────────


class _StubRouterWithUseCases:
    """Test double that mimics LLMKBRouter.route() output for a fixed tag set."""

    def __init__(self, use_cases, paths=None):
        from bhai.llm.kb_router import RouteResult

        self._result = RouteResult(paths=paths or [], use_cases=use_cases)
        self.received_history = None

    def route(self, transcript, top_n=3, threshold=0.0, conversation_history=None):
        self.received_history = conversation_history
        return self._result


def test_system_prompt_includes_use_case_block(stub_llm):
    """Active use-case tags inject their instruction block into the prompt."""
    stub_llm._kb_router = _StubRouterWithUseCases(use_cases=["grievance"])
    prompt = stub_llm._build_system_prompt(
        "hr_admin", transcript="supervisor pareshan kar raha hai"
    )
    assert "=== Active Use Cases" in prompt
    # The grievance block must be present (key phrase from the file)
    assert "Listen first" in prompt


def test_system_prompt_multi_use_cases_concatenated(stub_llm):
    """Multiple tags inject multiple blocks under one heading."""
    stub_llm._kb_router = _StubRouterWithUseCases(use_cases=["grievance", "general"])
    prompt = stub_llm._build_system_prompt(
        "hr_admin", transcript="supervisor se jhagda, aur ek jagah bata"
    )
    assert "Grievance" in prompt
    assert "General" in prompt


def test_system_prompt_no_use_cases_means_no_block(stub_llm):
    """Empty use-case list → no `Active Use Cases` heading."""
    stub_llm._kb_router = _StubRouterWithUseCases(use_cases=[])
    prompt = stub_llm._build_system_prompt("hr_admin", transcript="नमस्ते")
    assert "=== Active Use Cases" not in prompt


# ── _parse_structured_output (cot / out / escalate contract) ──────────


def test_parse_structured_output_valid():
    raw = '{"cot": "user is sad, be gentle", "out": "अरे, क्या हुआ? बताओ ना।"}'
    cot, out, escalate = BaseLLM._parse_structured_output(raw)
    assert cot == "user is sad, be gentle"
    assert out == "अरे, क्या हुआ? बताओ ना।"
    assert escalate is False


def test_parse_structured_output_strips_code_fence():
    raw = '```json\n{"cot": "x", "out": "नमस्ते"}\n```'
    _cot, out, _esc = BaseLLM._parse_structured_output(raw)
    assert out == "नमस्ते"


def test_parse_structured_output_ignores_surrounding_prose():
    raw = 'Sure!\n{"cot": "x", "out": "ठीक है"} Hope that helps.'
    _cot, out, _esc = BaseLLM._parse_structured_output(raw)
    assert out == "ठीक है"


def test_parse_structured_output_regex_fallback_on_broken_json():
    # Unterminated object (no closing brace) — json.loads fails, regex recovers out.
    raw = '{"cot": "thinking { broken", "out": "सब बढ़िया"'
    _cot, out, _esc = BaseLLM._parse_structured_output(raw)
    assert out == "सब बढ़िया"


def test_parse_structured_output_handles_escaped_quotes():
    raw = '{"cot": "x", "out": "उसने कहा \\"हाँ\\""}'
    _cot, out, _esc = BaseLLM._parse_structured_output(raw)
    assert out == 'उसने कहा "हाँ"'


def test_parse_structured_output_escalate_true():
    raw = '{"cot": "user consented to email", "out": "Team ko email kar rahi hoon.", "escalate": true}'
    _cot, out, escalate = BaseLLM._parse_structured_output(raw)
    assert out == "Team ko email kar rahi hoon."
    assert escalate is True


def test_parse_structured_output_escalate_regex_fallback():
    # Broken JSON (no closing brace) — escalate still recovered via regex.
    raw = '{"cot": "x", "out": "ठीक है", "escalate": true'
    _cot, out, escalate = BaseLLM._parse_structured_output(raw)
    assert out == "ठीक है"
    assert escalate is True


def test_parse_structured_output_unparseable_returns_empty():
    assert BaseLLM._parse_structured_output("totally not json") == ("", "", False)


def test_parse_structured_output_empty_input():
    assert BaseLLM._parse_structured_output("") == ("", "", False)


# ── generate() / generate_with_emotions() use "out", never "cot" ──────


class JsonStubLLM(BaseLLM):
    """Stub that returns a fixed raw payload, to exercise the JSON contract."""

    model_name = "json-stub"

    def __init__(self, cfg, kb, payload):
        super().__init__(cfg, knowledge_base_dir=kb)
        self._payload = payload

    def _call_api(self, system_prompt: str, user_message: str) -> str:
        return self._payload


def test_generate_uses_out_and_never_leaks_cot(tmp_knowledge_base):
    cfg = load_config()
    payload = '{"cot": "internal reasoning that must NOT leak", "out": "नमस्ते भाई!"}'
    llm = JsonStubLLM(cfg, tmp_knowledge_base, payload)
    result = llm.generate("hi")
    assert result["text"] == "नमस्ते भाई!"
    assert "internal reasoning" not in result["text"]
    assert result["cot"] == "internal reasoning that must NOT leak"
    assert result["parsed"] is True


def test_generate_falls_back_safely_when_unparseable(tmp_knowledge_base):
    cfg = load_config()
    llm = JsonStubLLM(cfg, tmp_knowledge_base, "this is not json at all")
    result = llm.generate("hi")
    # Never delivers the raw text; uses the safe canned fallback.
    assert result["text"]
    assert "not json" not in result["text"]
    # parsed=False signals callers (e.g. nudges) to skip rather than send it.
    assert result["parsed"] is False


def test_generate_strips_emoji_from_out(tmp_knowledge_base):
    """End-to-end: a model that returns emojis in `out` produces text
    without them, while cot and the rest of the parsed result flow
    through normally."""
    cfg = load_config()
    payload = (
        '{"cot": "internal reasoning — 🙏 emoji here is fine, cot never reaches TTS", '
        '"out": "Namaste 🙏 Manimala ji! आज का दिन कैसा रहा? 😊"}'
    )
    llm = JsonStubLLM(cfg, tmp_knowledge_base, payload)
    result = llm.generate("hi")
    assert result["parsed"] is True
    # No emoji codepoints in any user-facing text.
    assert "🙏" not in result["text"]
    assert "😊" not in result["text"]
    # Devanagari and ASCII survive.
    assert "Namaste" in result["text"]
    assert "Manimala ji" in result["text"]
    assert "आज का दिन कैसा रहा" in result["text"]
    # cot is unaffected — it's reasoning, never spoken.
    assert "🙏" in result["cot"]


def test_generate_strips_thread_blocks_from_out(tmp_knowledge_base):
    """Regression for the dev→v2 merge: `<thread>` blocks live INSIDE `out`
    (like `<memory>`), so the structured path must strip them from the spoken
    text — otherwise TTS reads "thread open ..." aloud — while still parsing
    them into thread_patches from the raw payload."""
    cfg = load_config()
    payload = (
        '{"cot": "x", "out": "अच्छा, तो saree का काम कैसा चल रहा है?\\n'
        "<memory>fact: runs a saree business</memory>\\n"
        '<thread>open: saree_business_expansion / ₹1L loan plan for Surat supplier</thread>"}'
    )
    llm = JsonStubLLM(cfg, tmp_knowledge_base, payload)
    result = llm.generate("hi")
    assert result["parsed"] is True
    # Neither block kind leaks into the spoken reply.
    assert "<thread>" not in result["text"]
    assert "<memory>" not in result["text"]
    assert "saree_business_expansion" not in result["text"]
    # The actual Hindi reply survives.
    assert "saree का काम कैसा चल रहा है" in result["text"]
    # Threads are still parsed from raw, so the proactive layer sees them.
    patches = result["thread_patches"]
    assert patches and patches[0].op == "open"
    assert patches[0].topic == "saree_business_expansion"


def test_generate_strips_emoji_from_markdown_emphasis(tmp_knowledge_base):
    """`*✨*` becomes empty: markdown strips the asterisks first, emoji-scrub
    removes the sparkle — no stray asterisks left orphaned."""
    cfg = load_config()
    payload = '{"cot": "x", "out": "*✨* ठीक है ना?"}'
    llm = JsonStubLLM(cfg, tmp_knowledge_base, payload)
    result = llm.generate("hi")
    assert result["text"].strip() == "ठीक है ना?"
    assert "*" not in result["text"]
    assert "✨" not in result["text"]


def test_generate_with_emotions_returns_single_neutral_segment(tmp_knowledge_base):
    cfg = load_config()
    payload = '{"cot": "x", "out": "ठीक है ना?"}'
    llm = JsonStubLLM(cfg, tmp_knowledge_base, payload)
    result = llm.generate_with_emotions("hi")
    assert result["text"] == "ठीक है ना?"
    assert result["segments"] == [{"text": "ठीक है ना?", "emotion": "neutral"}]


class SequenceStubLLM(BaseLLM):
    """Stub that returns a different payload per call, to exercise retries."""

    model_name = "seq-stub"

    def __init__(self, cfg, kb, payloads):
        super().__init__(cfg, knowledge_base_dir=kb)
        self._payloads = list(payloads)
        self.calls = 0

    def _call_api(self, system_prompt: str, user_message: str) -> str:
        payload = self._payloads[min(self.calls, len(self._payloads) - 1)]
        self.calls += 1
        return payload


def test_generate_retries_on_cot_parse_failure_then_succeeds(tmp_knowledge_base):
    cfg = load_config()
    # First call returns garbage; the re-roll returns valid JSON.
    llm = SequenceStubLLM(
        cfg,
        tmp_knowledge_base,
        ["garbage, not json", '{"cot": "x", "out": "अब ठीक है!"}'],
    )
    result = llm.generate("hi")
    assert result["text"] == "अब ठीक है!"
    assert llm.calls >= 2  # it actually retried


def test_generate_stops_retrying_after_max_attempts(tmp_knowledge_base):
    cfg = load_config()
    cfg.llm_json_max_attempts = 2  # cap retries for the test
    llm = SequenceStubLLM(cfg, tmp_knowledge_base, ["still not json"])
    result = llm.generate("hi")
    # Gave up to the safe fallback, and did NOT loop forever.
    assert result["text"]
    assert "not json" not in result["text"]
    assert llm.calls == 2


def test_generate_propagates_escalate_flag(tmp_knowledge_base):
    cfg = load_config()
    payload = (
        '{"cot": "user consented", "out": "Team ko email kar rahi hoon.", '
        '"escalate": true}'
    )
    llm = JsonStubLLM(cfg, tmp_knowledge_base, payload)
    result = llm.generate("please email the team")
    assert result["escalate"] is True
    assert result["text"] == "Team ko email kar rahi hoon."


def test_generate_escalate_defaults_false_when_absent(tmp_knowledge_base):
    cfg = load_config()
    payload = '{"cot": "x", "out": "अच्छा, बताओ।"}'
    llm = JsonStubLLM(cfg, tmp_knowledge_base, payload)
    result = llm.generate("hi")
    assert result["escalate"] is False
