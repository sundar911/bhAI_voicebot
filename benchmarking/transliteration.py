"""
Transliteration utilities for converting Romanized Hindi to Devanagari.
Uses indic-transliteration for reliable ITRANS-based conversion.
"""

from typing import List

# Lazy loading
_sanscript = None


def _get_sanscript():
    """Lazy load the sanscript module."""
    global _sanscript
    if _sanscript is None:
        try:
            from indic_transliteration import sanscript
            _sanscript = sanscript
        except ImportError:
            raise ImportError(
                "indic-transliteration not installed. "
                "Run: uv pip install indic-transliteration"
            )
    return _sanscript


def transliterate_sentence(text: str) -> str:
    """
    Transliterate a Romanized Hindi sentence to Devanagari.
    Uses ITRANS scheme which is common for Hindi typing.

    Args:
        text: Romanized Hindi text (e.g., "mera paisa kyun kata")

    Returns:
        Devanagari text (e.g., "मेरा पैसा क्युं काटा")
    """
    if not text or not text.strip():
        return ""

    sanscript = _get_sanscript()

    # Preprocess common informal spellings to ITRANS
    text = _normalize_to_itrans(text.strip())

    return sanscript.transliterate(
        text,
        sanscript.ITRANS,
        sanscript.DEVANAGARI
    )


def _normalize_to_itrans(text: str) -> str:
    """
    Normalize common informal spellings to ITRANS scheme.

    This handles common ways people type Hindi in Roman script:
    - 'aa' stays as 'aa' (already ITRANS for आ)
    - 'ee' -> 'ii' for ई
    - 'oo' -> 'uu' for ऊ
    - Common words get special handling
    """
    # Word-level substitutions (order matters - longer matches first)
    # These map common informal Hindi spellings to ITRANS
    word_substitutions = {
        # Pronouns
        "mera": "meraa",
        "meri": "merii",
        "tera": "teraa",
        "teri": "terii",
        "hamara": "hamaaraa",
        "tumhara": "tumhaaraa",
        "apna": "apnaa",
        "apni": "apnii",
        "mujhe": "mujhe",
        "tujhe": "tujhe",
        "unhe": "unhe.n",
        "inhe": "inhe.n",

        # Common verbs
        "karna": "karanaa",
        "karta": "karataa",
        "karti": "karatii",
        "hona": "honaa",
        "hota": "hotaa",
        "hoti": "hotii",
        "jana": "jaanaa",
        "jata": "jaataa",
        "jati": "jaatii",
        "ana": "aanaa",
        "ata": "aataa",
        "ati": "aatii",
        "lena": "lenaa",
        "leta": "letaa",
        "leti": "letii",
        "dena": "denaa",
        "deta": "detaa",
        "deti": "detii",
        "milna": "milanaa",
        "milta": "milataa",
        "milti": "milatii",
        "mila": "milaa",
        "mili": "milii",
        "kata": "kaTaa",
        "kate": "kaTe",
        "katna": "kaTanaa",
        "nikalna": "nikaalanaa",
        "nikalti": "nikaalatii",
        "nikalta": "nikaalataa",
        "lagta": "lagataa",
        "lagti": "lagatii",
        "laga": "lagaa",
        "lagi": "lagii",

        # Question words
        "kya": "kyaa",
        "kyu": "kyo.n",
        "kyun": "kyo.n",
        "kyon": "kyo.n",
        "kab": "kaba",
        "kaha": "kahaa.n",
        "kahan": "kahaa.n",
        "kaun": "kauna",
        "kaise": "kaise",
        "kitna": "kitanaa",
        "kitni": "kitanii",
        "kitne": "kitane",

        # Common particles (add trailing 'a' where needed for ITRANS)
        "hai": "hai",
        "hain": "hai.n",
        "tha": "thaa",
        "thi": "thii",
        "the": "the",
        "nahi": "nahii.n",
        "nahin": "nahii.n",
        "mein": "mei.n",
        "main": "mai.n",
        "hum": "hama",
        "tum": "tuma",
        "aap": "aapa",
        "woh": "vaha",
        "yeh": "yaha",
        "bhi": "bhii",
        "hi": "hii",
        "ka": "kaa",
        "ki": "kii",
        "ke": "ke",
        "ko": "ko",
        "se": "se",
        "pe": "pe",
        "par": "para",
        "tak": "taka",
        "aur": "aura",
        "ya": "yaa",
        "lekin": "lekina",
        "agar": "agara",
        "jab": "jaba",
        "tab": "taba",
        "abhi": "abhii",
        "kal": "kala",
        "parso": "parso.n",
        "aaj": "aaja",

        # HR/Work related
        "paisa": "paisaa",
        "paise": "paise",
        "chutti": "ChuTTii",
        "aadhar": "aadhaara",
        "aadhaar": "aadhaara",
        "pf": "pii efa",
        "esi": "ii esa aai",
        "milega": "milegaa",
        "milegi": "milegii",
        "hua": "huaa",
        "hui": "huii",
        "hue": "hue",
        "lagega": "lagegaa",
        "lagegi": "lagegii",
        "karein": "kare.n",
        "karo": "karo",
        "kijiye": "kiijiye",

        # Common nouns (note: ITRANS needs final 'a' for schwa)
        "kaam": "kaama",
        "ghar": "ghara",
        "din": "dina",
        "raat": "raata",
        "log": "loga",
        "banda": "bandaa",
        "bandi": "bandii",
        "baat": "baata",
        "sawal": "savaala",
        "jawab": "javaaba",

        # More verbs
        "loon": "luu.n",
        "lun": "luu.n",
        "karun": "karuu.n",
        "jaun": "jaau.n",
        "aun": "aauu.n",
        "paungi": "paauu.ngii",
        "paunga": "paauu.ngaa",
        "sakta": "sakataa",
        "sakti": "sakatii",
        "sakte": "sakate",
        "chahiye": "chaahiye",
        "chahte": "chaahate",
        "chahti": "chaahatii",

        # Numbers (common)
        "ek": "eka",
        "do": "do",
        "teen": "tiina",
        "char": "chaara",
        "panch": "paa.ncha",
        "chhe": "Chaha",
        "saat": "saata",
        "aath": "aaTha",
        "nau": "nau",
        "das": "dasa",
    }

    # English words to keep as-is (common in Hinglish)
    english_words = {
        "salary", "leave", "card", "update", "office", "time",
        "phone", "mobile", "email", "computer", "bank", "account",
        "form", "document", "problem", "issue", "help", "please",
        "sir", "madam", "ok", "yes", "no", "sorry", "thank", "thanks",
    }

    # Character-level substitutions for patterns
    char_substitutions = {
        "ee": "ii",
        "oo": "uu",
    }

    result = text.lower()

    # Apply word-level substitutions
    words = result.split()
    normalized_words = []
    for word in words:
        if word in word_substitutions:
            normalized_words.append(word_substitutions[word])
        elif word in english_words:
            # Keep English words as-is (will be passed through)
            normalized_words.append(word)
        else:
            # Apply character substitutions for unknown words
            normalized_word = word
            for pattern, replacement in char_substitutions.items():
                normalized_word = normalized_word.replace(pattern, replacement)
            normalized_words.append(normalized_word)

    return " ".join(normalized_words)


def transliterate_word(word: str, top_k: int = 5) -> List[str]:
    """
    Transliterate a single word and return the result.
    For indic-transliteration, we return single result since it's deterministic.

    Args:
        word: Romanized Hindi word (e.g., "kyun")
        top_k: Not used (kept for API compatibility)

    Returns:
        List with single Devanagari word
    """
    if not word or not word.strip():
        return []

    result = transliterate_sentence(word)
    return [result] if result else [word]


def transliterate_with_alternatives(text: str, top_k: int = 3) -> dict:
    """
    Transliterate text (returns single result for deterministic transliteration).

    Args:
        text: Romanized Hindi text
        top_k: Not used (kept for API compatibility)

    Returns:
        Dictionary with:
            - "sentence": Transliterated sentence
            - "words": Dict mapping each word to its transliteration
    """
    if not text or not text.strip():
        return {"sentence": "", "words": {}}

    sentence = transliterate_sentence(text)

    words = text.strip().split()
    word_results = {}
    for word in words:
        if word:
            word_results[word] = [transliterate_sentence(word)]

    return {
        "sentence": sentence,
        "words": word_results
    }


# Simple test
if __name__ == "__main__":
    test_cases = [
        "mera paisa kyun kata",
        "chutti kaise loon",
        "aadhar kab milega",
        "mujhe nahi mili",
        "main kal nahi aa paungi",
        "kya hua",
        "kitna din lagega",
        "hum kab tak wait karein",
    ]

    print("Transliteration Test:")
    print("-" * 50)
    for text in test_cases:
        result = transliterate_sentence(text)
        print(f"{text}")
        print(f"  -> {result}")
        print()
