#!/usr/bin/env python3
"""
Text normalization pipeline for fair Hindi/Indic ASR evaluation.

Applied to BOTH hypothesis and reference before computing WER/CER so that
surface formatting differences (punctuation, digit style, diacritic variants)
don't pollute the metrics.

Each normalization step is exposed as a standalone function so that
error_analysis.py can measure the incremental impact of each layer.
"""

import re
import unicodedata

# ---------------------------------------------------------------------------
# Optional heavy imports — guarded so the module is importable even if the
# libraries aren't installed (the functions raise clear errors instead).
# ---------------------------------------------------------------------------

_indic_normalizer = None


def _get_indic_normalizer():
    """Lazy-load IndicNormalizer for Hindi."""
    global _indic_normalizer
    if _indic_normalizer is None:
        try:
            from indicnlp.normalize.indic_normalize import IndicNormalizerFactory
            factory = IndicNormalizerFactory()
            _indic_normalizer = factory.get_normalizer("hi")
        except ImportError:
            raise ImportError(
                "indic-nlp-library is required for Indic normalization.\n"
                "Install: pip install indic-nlp-library"
            )
    return _indic_normalizer


# ---------------------------------------------------------------------------
# Punctuation
# ---------------------------------------------------------------------------

# All punctuation that ASR models might emit (Latin + Devanagari + currency)
_PUNCT_RE = re.compile(
    r"[,.\?!;:।\|\"'""''()（）\[\]{}<>…–—\-/\\~`@#$%^&*+=_₹₨$€£¥]"
)


def strip_punctuation(text: str) -> str:
    """Remove all punctuation characters."""
    return _PUNCT_RE.sub("", text)


# ---------------------------------------------------------------------------
# Numbers → Devanagari words
# ---------------------------------------------------------------------------

# Matches standalone digit sequences (optionally with commas: 50,000)
_NUM_RE = re.compile(r"\b[\d,]+\.?\d*\b")


# Hindi has unique words for every integer 0–99 (not composable like English)
_HINDI_ONES = [
    "", "एक", "दो", "तीन", "चार", "पाँच", "छह", "सात", "आठ", "नौ",
    "दस", "ग्यारह", "बारह", "तेरह", "चौदह", "पंद्रह", "सोलह", "सत्रह",
    "अठारह", "उन्नीस", "बीस", "इक्कीस", "बाईस", "तेईस", "चौबीस",
    "पच्चीस", "छब्बीस", "सत्ताईस", "अट्ठाईस", "उनतीस", "तीस",
    "इकतीस", "बत्तीस", "तैंतीस", "चौंतीस", "पैंतीस", "छत्तीस",
    "सैंतीस", "अड़तीस", "उनतालीस", "चालीस", "इकतालीस", "बयालीस",
    "तैंतालीस", "चवालीस", "पैंतालीस", "छियालीस", "सैंतालीस",
    "अड़तालीस", "उनचास", "पचास", "इक्यावन", "बावन", "तिरपन",
    "चौवन", "पचपन", "छप्पन", "सत्तावन", "अट्ठावन", "उनसठ", "साठ",
    "इकसठ", "बासठ", "तिरसठ", "चौंसठ", "पैंसठ", "छियासठ", "सड़सठ",
    "अड़सठ", "उनहत्तर", "सत्तर", "इकहत्तर", "बहत्तर", "तिहत्तर",
    "चौहत्तर", "पचहत्तर", "छिहत्तर", "सतहत्तर", "अठहत्तर", "उनासी",
    "अस्सी", "इक्यासी", "बयासी", "तिरासी", "चौरासी", "पचासी",
    "छियासी", "सत्तासी", "अट्ठासी", "नवासी", "नब्बे", "इक्यानवे",
    "बानवे", "तिरानवे", "चौरानवे", "पचानवे", "छियानवे", "सत्तानवे",
    "अट्ठानवे", "निन्यानवे",
]

# Indian number system: सौ (100), हजार (1000), लाख (1,00,000), करोड़ (1,00,00,000)
_INDIAN_GROUPS = [
    (10_000_000, "करोड़"),
    (100_000, "लाख"),
    (1_000, "हजार"),
    (100, "सौ"),
]


def _int_to_hindi(n: int) -> str:
    """Convert a non-negative integer to Hindi words (Indian number system)."""
    if n < 0:
        return "माइनस " + _int_to_hindi(-n)
    if n == 0:
        return "शून्य"
    if n < 100:
        return _HINDI_ONES[n]

    parts: list[str] = []
    for divisor, label in _INDIAN_GROUPS:
        if n >= divisor:
            q = n // divisor
            parts.append(f"{_int_to_hindi(q)} {label}")
            n %= divisor
    if n > 0:
        parts.append(_HINDI_ONES[n])
    return " ".join(parts)


def _digits_to_hindi_words(match: re.Match) -> str:
    """Convert a matched digit string to Hindi words."""
    raw = match.group().replace(",", "")
    try:
        if "." in raw:
            # Decimal: convert integer and fractional parts separately
            int_part, frac_part = raw.split(".", 1)
            int_val = int(int_part) if int_part else 0
            frac_val = int(frac_part) if frac_part else 0
            if 0 <= int_val <= 99_99_99_999 and 0 <= frac_val <= 99_99_99_999:
                return f"{_int_to_hindi(int_val)} दशमलव {_int_to_hindi(frac_val)}"
            return match.group()
        num = int(raw)
        if 0 <= num <= 99_99_99_999:
            return _int_to_hindi(num)
        return match.group()
    except (ValueError, OverflowError):
        return match.group()


def normalize_numbers(text: str) -> str:
    """Replace digit sequences with Hindi word equivalents."""
    return _NUM_RE.sub(_digits_to_hindi_words, text)


# ---------------------------------------------------------------------------
# Time-aware normalization  ("6.30 बजे" → "साढ़े छह बजे")
# ---------------------------------------------------------------------------

# Matches patterns like "6.30 बजे" or "4.15बजे" (with optional space)
_TIME_RE = re.compile(r"(\d{1,2})\.(\d{2})\s*बजे")


def _time_to_hindi(match: re.Match) -> str:
    """Convert a time pattern like '6.30 बजे' to Hindi time words."""
    hour = int(match.group(1))
    minutes = int(match.group(2))

    if hour < 1 or hour > 12:
        return match.group()  # out of range, leave as-is

    hour_word = _int_to_hindi(hour)

    if minutes == 0:
        # 4.00 बजे → चार बजे
        return f"{hour_word} बजे"
    elif minutes == 15:
        # 3.15 बजे → सवा तीन बजे
        return f"सवा {hour_word} बजे"
    elif minutes == 30:
        # Special irregular forms
        if hour == 1:
            return "डेढ़ बजे"      # 1.30 = डेढ़
        elif hour == 2:
            return "ढाई बजे"      # 2.30 = ढाई
        else:
            return f"साढ़े {hour_word} बजे"
    elif minutes == 45:
        # X.45 बजे → पौने (X+1) बजे
        next_hour = hour + 1 if hour < 12 else 1
        next_word = _int_to_hindi(next_hour)
        return f"पौने {next_word} बजे"
    else:
        # Other minutes: "X बजकर Y मिनट"
        min_word = _int_to_hindi(minutes)
        return f"{hour_word} बजकर {min_word} मिनट"


def normalize_time(text: str) -> str:
    """Convert time expressions like '6.30 बजे' to Hindi words."""
    return _TIME_RE.sub(_time_to_hindi, text)


# ---------------------------------------------------------------------------
# Currency-aware normalization  ("₹1000" → "एक हजार रुपये")
# ---------------------------------------------------------------------------

# Matches ₹ followed by digits (with optional commas)
_CURRENCY_RE = re.compile(r"₹\s*([\d,]+)")


def _currency_to_hindi(match: re.Match) -> str:
    """Convert '₹1000' to 'एक हजार रुपये'."""
    raw = match.group(1).replace(",", "")
    try:
        num = int(raw)
        if 0 <= num <= 99_99_99_999:
            return f"{_int_to_hindi(num)} रुपये"
        return match.group()
    except (ValueError, OverflowError):
        return match.group()


def normalize_currency(text: str) -> str:
    """Convert currency expressions like '₹1000' to Hindi words + रुपये."""
    return _CURRENCY_RE.sub(_currency_to_hindi, text)


# ---------------------------------------------------------------------------
# Unicode / Indic script normalization
# ---------------------------------------------------------------------------

def normalize_unicode(text: str) -> str:
    """
    NFC normalization + IndicNormalizer for Devanagari.

    Handles: chandrabindu/anusvara, nukta, ZWJ/ZWNJ, multi-part vowel signs.
    """
    # Step 1: Unicode canonical composition
    text = unicodedata.normalize("NFC", text)

    # Step 2: Remove zero-width characters that some models insert
    text = text.replace("\u200b", "")  # zero-width space
    text = text.replace("\u200c", "")  # ZWNJ
    text = text.replace("\u200d", "")  # ZWJ
    text = text.replace("\ufeff", "")  # BOM

    # Step 3: Indic-specific normalization
    try:
        normalizer = _get_indic_normalizer()
        text = normalizer.normalize(text)
    except ImportError:
        pass  # graceful degradation — skip if library not installed

    return text


# ---------------------------------------------------------------------------
# Whitespace
# ---------------------------------------------------------------------------

_MULTI_SPACE_RE = re.compile(r"\s+")


def collapse_whitespace(text: str) -> str:
    """Collapse runs of whitespace into single spaces and strip edges."""
    return _MULTI_SPACE_RE.sub(" ", text).strip()


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def normalize_hindi(text: str) -> str:
    """
    Full normalization pipeline for Hindi ASR evaluation.

    Order matters:
    1. Unicode/Indic normalization (fixes encoding first)
    2. Time expressions ("6.30 बजे" → "साढ़े छह बजे")
    3. Currency expressions ("₹1000" → "एक हजार रुपये")
    4. Remaining numbers (digits → Hindi words)
    5. Strip punctuation (clean up remaining punct)
    6. Collapse whitespace (cleanup)
    """
    text = normalize_unicode(text)
    text = normalize_time(text)
    text = normalize_currency(text)
    text = normalize_numbers(text)
    text = strip_punctuation(text)
    text = collapse_whitespace(text)
    return text


# ---------------------------------------------------------------------------
# CLI: test the pipeline on a string
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    samples = [
        "हमें 4 बजे नाश्ता नहीं चाहिए, 6.30 बजे चाय और नाश्ता दोनों चाहिए।",
        "मेरा पेमेंट में ₹1000 कम आया है।",
        "1.30 बजे आना है",
        "2.30 बजे जाना है",
        "3.15 बजे मिलते हैं",
        "1.45 बजे निकलना है",
        "5.20 बजे आ जाओ",
        "मुझे 50000 रुपये चाहिए",
        "छब्बीस जनवरी 2024 को",
    ]

    if len(sys.argv) > 1:
        samples = [" ".join(sys.argv[1:])]

    for s in samples:
        print(f"  IN:  {s}")
        print(f"  OUT: {normalize_hindi(s)}")
        print()
