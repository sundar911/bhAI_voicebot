"""
Emotion tagging utilities for ElevenLabs TTS.

Converts structured LLM output (per-segment emotion annotations)
into text with embedded ElevenLabs audio tags.
"""

import re
from typing import Dict, List

# ElevenLabs audio tags — each influences ~4-5 words after placement
EMOTION_TAGS: Dict[str, str] = {
    "excited": "[excited]",
    "whisper": "[whispers]",
    "sigh": "[sighs]",
    "sad": "[crying]",
    "mischief": "[mischief]",
    "laugh": "[laughs]",
    "pause": "[pause]",
}

VALID_EMOTIONS = set(EMOTION_TAGS.keys()) | {"neutral"}

# Pattern matching any bracketed audio tag
_TAG_PATTERN = re.compile(r"\[[a-zA-Z\s]+\]")


def annotate_with_emotions(segments: List[dict]) -> str:
    """
    Convert segment dicts into a single string with ElevenLabs audio tags.

    Args:
        segments: List of dicts like [{"text": "...", "emotion": "excited"}, ...]
                  If emotion is None, empty, or "neutral", no tag is inserted.

    Returns:
        Single string with embedded audio tags, e.g.:
        "[excited] Arre waah! [pause] Batao kya hua."
    """
    # NOTE: ElevenLabs audio tags ([laughs], [sighs], etc.) are read literally
    # when surrounding text is Hindi/Hinglish — disabled until ElevenLabs
    # improves multilingual tag support. Segments still tracked for logging.
    parts = []
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        parts.append(text)

    return " ".join(parts)


def strip_emotion_tags(text: str) -> str:
    """Remove all bracketed audio tags from text (for logging/display)."""
    return _TAG_PATTERN.sub("", text).strip()
