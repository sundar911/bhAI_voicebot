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

# All punctuation that ASR models might emit (Latin + Devanagari)
_PUNCT_RE = re.compile(
    r"[,.\?!;:।\|\"'""''()（）\[\]{}<>…–—\-/\\~`@#$%^&*+=_]"
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
            return match.group()  # leave decimals as-is
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
    1. Unicode/Indic normalization (before anything else — fixes encoding)
    2. Strip punctuation (before number normalization — avoid "500." issues)
    3. Normalize numbers (digits → words)
    4. Collapse whitespace (cleanup)
    """
    text = normalize_unicode(text)
    text = strip_punctuation(text)
    text = normalize_numbers(text)
    text = collapse_whitespace(text)
    return text


# ---------------------------------------------------------------------------
# CLI: test the pipeline on a string
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    samples = [
        "हेलो मैडम, मैं चंदा देवी बोल रही हूँ। हमारे आधार कार्ड में यहाँ का एड्रेस डालने का है, हो जाएगा क्या?",
        "मुझे 50000 रुपये चाहिए",
        "छब्बीस जनवरी 2024 को",
        "मेरा PF amount जानना है",
    ]

    if len(sys.argv) > 1:
        samples = [" ".join(sys.argv[1:])]

    for s in samples:
        print(f"  IN:  {s}")
        print(f"  OUT: {normalize_hindi(s)}")
        print()
