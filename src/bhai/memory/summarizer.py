"""
LLM-based conversation summarization and fact extraction.
Runs periodically (every N user messages) to maintain rolling memory.
"""

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bhai.memory")

# Trigger summarization every N user messages
SUMMARIZE_EVERY_N = 5

SUMMARIZE_PROMPT = """Neeche ek user ki pichli baatcheet ka summary hai aur uske baad nayi baatcheet.

=== Puraana Summary ===
{old_summary}

=== Nayi Baatcheet ===
{recent_messages}

=== Instructions ===
1. Puraane summary ko nayi baatcheet ke saath update karo. 3-4 lines mein likho, Hindi mein.
2. Jo important facts hain (naam, parivaar, kaam, health, preferences) unko alag se list karo.
3. Response SIRF is format mein do:

SUMMARY:
[updated summary in 3-4 lines]

FACTS:
["fact 1", "fact 2", "fact 3"]

Bas itna. Koi aur text mat likho."""


def _format_messages(messages: List[Dict[str, str]]) -> str:
    """Format message list for the summarization prompt."""
    lines = []
    for msg in messages:
        role_label = "User" if msg["role"] == "user" else "bhAI"
        lines.append(f"{role_label}: {msg['content']}")
    return "\n".join(lines)


def _parse_summary_response(raw: str) -> Dict[str, Any]:
    """Parse the LLM's summary response into summary + facts."""
    summary = ""
    facts = []

    lines = raw.strip().split("\n")
    mode = None

    summary_lines = []
    facts_line = ""

    for line in lines:
        stripped = line.strip()
        if stripped.upper().startswith("SUMMARY:"):
            mode = "summary"
            rest = stripped[len("SUMMARY:") :].strip()
            if rest:
                summary_lines.append(rest)
        elif stripped.upper().startswith("FACTS:"):
            mode = "facts"
            rest = stripped[len("FACTS:") :].strip()
            if rest:
                facts_line = rest
        elif mode == "summary":
            if stripped:
                summary_lines.append(stripped)
        elif mode == "facts":
            if stripped:
                facts_line += stripped

    summary = " ".join(summary_lines).strip()

    # Parse facts JSON
    if facts_line:
        try:
            parsed = json.loads(facts_line)
            if isinstance(parsed, list):
                facts = [str(f) for f in parsed]
        except json.JSONDecodeError:
            # Fallback: treat as comma-separated
            facts = [f.strip().strip("\"'") for f in facts_line.split(",") if f.strip()]

    return {"summary": summary, "facts": facts}


def should_summarize(user_message_count: int) -> bool:
    """Check if we should trigger summarization based on message count."""
    return user_message_count > 0 and user_message_count % SUMMARIZE_EVERY_N == 0


def build_summarize_request(
    old_summary: str,
    recent_messages: List[Dict[str, str]],
) -> str:
    """Build the summarization prompt for the LLM."""
    if not old_summary:
        old_summary = "(Abhi tak koi summary nahi hai — yeh pehli baatcheet hai)"

    return SUMMARIZE_PROMPT.format(
        old_summary=old_summary,
        recent_messages=_format_messages(recent_messages),
    )


def parse_summary(raw_response: str) -> Dict[str, Any]:
    """Parse the LLM's summarization response."""
    result = _parse_summary_response(raw_response)

    if not result["summary"]:
        logger.warning("Failed to parse summary from LLM response, using raw text")
        result["summary"] = raw_response[:500]

    return result


def merge_facts(existing_facts: List[str], new_facts: List[str]) -> List[str]:
    """Merge new facts with existing ones, deduplicating."""
    # Simple dedup by normalized string comparison
    seen = set()
    merged = []
    for fact in existing_facts + new_facts:
        normalized = fact.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            merged.append(fact.strip())
    return merged
