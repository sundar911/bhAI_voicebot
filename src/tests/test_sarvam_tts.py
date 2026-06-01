"""
Tests for src/bhai/tts/sarvam_tts.py — focused on the pre-TTS
currency-normalization step. Sarvam's bulbul:v3 has no pronunciation for
``₹`` or "rupees" so we substitute the Devanagari ``रुपए`` first.

We test the pure normalizer here (no network); the synthesize() wiring is
covered by integration smoke elsewhere.
"""

from bhai.tts.sarvam_tts import detect_language_code, normalize_currency_for_sarvam


def test_normalize_currency_single_amount():
    """₹500 → 500 रुपए."""
    assert normalize_currency_for_sarvam("कीमत ₹500 है") == "कीमत 500 रुपए है"


def test_normalize_currency_range_with_hyphen():
    """₹700-800 → 700 से 800 रुपए."""
    assert (
        normalize_currency_for_sarvam("Bombay Central के पास ₹700-800 में खाना")
        == "Bombay Central के पास 700 से 800 रुपए में खाना"
    )


def test_normalize_currency_range_with_en_dash():
    """₹150–180 (en dash) → 150 से 180 रुपए."""
    assert (
        normalize_currency_for_sarvam("₹150–180 per person")
        == "150 से 180 रुपए per person"
    )


def test_normalize_currency_amount_with_comma():
    """₹1,500 → 1,500 रुपए (commas preserved)."""
    assert normalize_currency_for_sarvam("₹1,500") == "1,500 रुपए"


def test_normalize_currency_amount_with_space():
    """₹ 500 (with space) → 500 रुपए."""
    assert normalize_currency_for_sarvam("₹ 500") == "500 रुपए"


def test_normalize_currency_rs_prefix():
    """Rs.500 / Rs 500 → रुपए 500."""
    assert normalize_currency_for_sarvam("Rs.500") == "रुपए 500"
    assert normalize_currency_for_sarvam("Rs 500") == "रुपए 500"
    assert normalize_currency_for_sarvam("कीमत Rs. 800 है") == "कीमत रुपए 800 है"


def test_normalize_currency_english_word():
    """'rupees' / 'rupee' / 'Rupees' → रुपए."""
    assert normalize_currency_for_sarvam("500 rupees") == "500 रुपए"
    assert normalize_currency_for_sarvam("one rupee") == "one रुपए"
    assert normalize_currency_for_sarvam("Rupees 500") == "रुपए 500"


def test_normalize_currency_standalone_glyph():
    """Lone ₹ with no following digits → रुपए (rare but safe)."""
    assert normalize_currency_for_sarvam("बस ₹ की बात है") == "बस रुपए  की बात है"


def test_normalize_currency_no_currency_text_unchanged():
    """Text without any currency markers is returned unchanged."""
    text = "आज खाने में क्या बनाया है?"
    assert normalize_currency_for_sarvam(text) == text


def test_normalize_currency_empty_string():
    """Empty/None input is handled gracefully."""
    assert normalize_currency_for_sarvam("") == ""


def test_normalize_currency_multiple_amounts_in_one_message():
    """Multiple ₹ amounts in the same text all get normalized."""
    text = "Thali ₹150-180 per person, Chinese ₹200 alag से"
    expected = "Thali 150 से 180 रुपए per person, Chinese 200 रुपए alag से"
    assert normalize_currency_for_sarvam(text) == expected


def test_normalize_currency_devanagari_form_already_present_unchanged():
    """If the text already has रुपए, leave it alone — no double-substitution."""
    text = "कीमत 500 रुपए है"
    assert normalize_currency_for_sarvam(text) == text


def test_normalize_currency_rs_must_have_digit_after():
    """'Rishi' / 'Rs' as part of a name must not trip the regex.
    Only Rs followed by whitespace+digit gets substituted."""
    assert "Rishi" in normalize_currency_for_sarvam("Rishi Sir")
    # 'Rs' followed by a non-digit word: should not substitute
    assert normalize_currency_for_sarvam("Rs corp") == "Rs corp"


# ── detect_language_code ──────────────────────────────────────────────


def test_detect_lang_devanagari_to_hindi():
    """Devanagari script (Hindi/Marathi) → hi-IN."""
    assert detect_language_code("नमस्ते भाई कैसे हो") == "hi-IN"


def test_detect_lang_tamil():
    """Tamil script → ta-IN. This is the 2026-05-27 dev-test case."""
    assert detect_language_code("ஆமா, தமிழ்ல பேசலாமே") == "ta-IN"


def test_detect_lang_telugu():
    assert detect_language_code("నమస్తే అన్నా బాగున్నారా") == "te-IN"


def test_detect_lang_malayalam():
    assert detect_language_code("നമസ്കാരം ഏട്ടാ") == "ml-IN"


def test_detect_lang_kannada():
    assert detect_language_code("ನಮಸ್ಕಾರ ಅಣ್ಣ") == "kn-IN"


def test_detect_lang_bengali():
    assert detect_language_code("নমস্কার দাদা") == "bn-IN"


def test_detect_lang_gujarati():
    assert detect_language_code("નમસ્તે ભાઈ") == "gu-IN"


def test_detect_lang_punjabi():
    assert detect_language_code("ਸਤ ਸ੍ਰੀ ਅਕਾਲ ਭਾਈ") == "pa-IN"


def test_detect_lang_odia():
    assert detect_language_code("ନମସ୍କାର ଭାଇ") == "od-IN"


def test_detect_lang_empty_returns_default():
    assert detect_language_code("") == "hi-IN"
    assert detect_language_code("   ") == "hi-IN"


def test_detect_lang_pure_english_returns_en():
    """No Indic script + Latin letters → en-IN (don't force Hindi voice)."""
    assert detect_language_code("Hello there friend") == "en-IN"


def test_detect_lang_mixed_picks_dominant_indic():
    """Tamil dominant over English → ta-IN (the actual dev-test case
    had 'Hindi-Marathi நல்லா' mixed; Tamil should win)."""
    text = "Hindi-Marathi நல்லா வருது எனக்கு Sundar"
    assert detect_language_code(text) == "ta-IN"


def test_detect_lang_mixed_devanagari_with_english_words():
    """Hindi reply with embedded English words (PAN, WhatsApp) →
    still hi-IN, not en-IN."""
    text = "PAN card के लिए ये documents लगेंगे"
    assert detect_language_code(text) == "hi-IN"


def test_detect_lang_custom_default():
    """The default kwarg is honored when no script signal exists."""
    assert detect_language_code("", default="mr-IN") == "mr-IN"
