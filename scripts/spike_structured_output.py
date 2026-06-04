"""
Spike test: verify Anthropic's `output_config.format` (GA 2026-02-04) is a
viable replacement for the assistant-prefill JSON envelope on
claude-sonnet-4-6 — alongside adaptive thinking and the web_search server
tool, both of which we already use in production.

Context: 4.6 hard-rejects assistant prefill (`400: This model does not
support assistant message prefill`), which kills Nibraas's `{"cot": ...}`
prefill approach. Forced `tool_choice` is also ruled out — it errors when
extended thinking is on. `output_config.format` uses grammar-constrained
decoding (token-level schema masking) without the `tool_choice` override,
so it's the only path left that gives reliable structured output AND
keeps thinking + web_search usable. This script proves whether that
actually holds in practice on 4.6, not just on paper.

Probes in increasing order of risk:
  1. Plain `output_config.format` — sanity that the feature works at all
  2. + adaptive thinking
  3. + web_search server tool (no thinking) — the ambiguous case: docs
     say `output_config.format` 400s if "citations" are enabled, and
     web_search auto-attaches them
  4. + thinking AND web_search — the production combination
  5. Reasoning-heavy prompt to verify CoT does NOT bleed into `out`

If any test 400s or leaks CoT, the failure tells us the next step
(workaround, separate call, etc.). If all five pass, the migration is
green-lit on the architectural side.

Run:  uv run python scripts/spike_structured_output.py
Cost: ~$0.10-$0.30 in API calls.
"""

import json
import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
WEB_SEARCH_TOOL = os.getenv("WEB_SEARCH_TOOL_NAME", "web_search_20250305")

client = anthropic.Anthropic()

# Mirrors what bhAI's production schema would look like — four required
# fields, additionalProperties locked off so the model can't sneak extras
# past the parser.
RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "out": {
            "type": "string",
            "description": (
                "The message the user hears, in the user's language "
                "(Hindi in Devanagari for these tests). Goes straight to TTS."
            ),
        },
        "memory_patches": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "List of short facts to remember about the user. "
                "Empty list if nothing new this turn."
            ),
        },
        "escalate": {
            "type": "boolean",
            "description": (
                "True ONLY if the user has explicitly consented to having "
                "the team emailed about this. Default false."
            ),
        },
        "escalate_category": {
            "type": "string",
            "enum": ["docs_bc", "docs_midc", "docs_unknown", "grievance", "none"],
            "description": "Routing category; 'none' when escalate is false.",
        },
    },
    "required": ["out", "memory_patches", "escalate", "escalate_category"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You are bhAI, a warm Hindi-speaking voice assistant for women artisans "
    "in Mumbai. Reply naturally in conversational Hindi (Devanagari script). "
    "Every response is a single JSON object matching the provided schema: "
    "`out` carries the spoken reply, `memory_patches` is an array of short "
    "facts to remember (empty if nothing new), `escalate` is true only when "
    "the user has explicitly said yes to emailing the team, and "
    "`escalate_category` is 'none' when `escalate` is false."
)


# ──────────────── Helpers ────────────────


def _final_text_block(response) -> str | None:
    """Return the text from the LAST text content block.

    With web_search, the response may contain interleaved
    `server_tool_use`, `web_search_tool_result`, and `text` blocks; the
    structured-output JSON is in the FINAL text block after the search
    has resolved.
    """
    text_blocks = [b for b in response.content if getattr(b, "type", None) == "text"]
    if not text_blocks:
        return None
    return text_blocks[-1].text


def _summarise(label: str, response) -> dict:
    print(f"\n{'=' * 72}")
    print(f"TEST: {label}")
    print(f"{'=' * 72}")
    print(f"stop_reason   : {response.stop_reason}")
    print(f"content blocks: {len(response.content)}")
    block_types: list[str] = []
    for block in response.content:
        block_types.append(getattr(block, "type", "?"))
    print(f"block sequence: {block_types}")

    raw = _final_text_block(response)
    if raw is None:
        print("⚠️  No text block found.")
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"⚠️  JSON parse failed: {e}")
        print(f"    raw text: {raw[:300]!r}")
        return {}

    out = parsed.get("out", "")
    print(f"out                : {out[:240]!r}")
    print(f"escalate           : {parsed.get('escalate')}")
    print(f"escalate_category  : {parsed.get('escalate_category')}")
    print(f"memory_patches     : {parsed.get('memory_patches')}")
    return parsed


def _check_cot_leak(parsed: dict) -> list[str]:
    """Scan `out` for reasoning-leak markers.

    Mirrors `_REASONING_LEAK_MARKERS` in base.py — anything that looks
    like the model narrating its own thought process to the user
    instead of just answering them.
    """
    if not parsed:
        return ["(no parsed output to scan)"]
    out = (parsed.get("out") or "").lower()
    markers = [
        "let me think",
        "let me ",
        "i should ",
        "i'll ",
        "i need to ",
        "the user is",
        "the user wants",
        "system prompt",
        "instruction says",
        "मुझे सोचना",
        "user को",
        "user चाहत",
        "मैं देख रही हूँ कि",
        "मुझे जवाब देना है",
    ]
    return [m for m in markers if m in out]


# ──────────────── Tests ────────────────


def test_1_plain() -> bool:
    """Sanity: does `output_config.format` work on 4.6 at all?"""
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": "नमस्ते भाई, कैसी हो?"}],
            extra_body={
                "output_config": {
                    "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}
                }
            },
        )
        _summarise("1. plain output_config.format", response)
        return True
    except Exception as e:
        print(f"\n❌ TEST 1 FAILED: {e!r}")
        return False


def test_2_with_thinking() -> bool:
    """`output_config.format` + adaptive thinking on 4.6."""
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "भाई, ₹1 lakh का loan लेना है, ₹8000 EMI, 14 महीने का। "
                        "अभी पुराना ₹5000 EMI का loan चल रहा है, 3 महीने बाक़ी हैं। "
                        "कर लूँ?"
                    ),
                }
            ],
            extra_body={
                "output_config": {
                    "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}
                },
                "thinking": {"type": "adaptive"},
            },
        )
        parsed = _summarise("2. + adaptive thinking", response)
        leaks = _check_cot_leak(parsed)
        if leaks:
            print(f"⚠️  CoT-leak markers in `out`: {leaks}")
        else:
            print("✓ no CoT-leak markers in `out`")
        return True
    except Exception as e:
        print(f"\n❌ TEST 2 FAILED: {e!r}")
        return False


def test_3_with_web_search() -> bool:
    """The ambiguous case — `output_config.format` + web_search (no thinking).

    Docs say `output_config.format` returns 400 if citations are enabled.
    web_search auto-attaches citations to its results. If this 400s, the
    error message will tell us whether web_search citations specifically
    are the trigger.
    """
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": "Borivali में Setu Kendra का exact address क्या है?",
                }
            ],
            tools=[
                {
                    "type": WEB_SEARCH_TOOL,
                    "name": "web_search",
                    "max_uses": 2,
                }
            ],
            extra_body={
                "output_config": {
                    "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}
                }
            },
        )
        _summarise("3. + web_search server tool", response)
        return True
    except Exception as e:
        print(f"\n❌ TEST 3 FAILED: {e!r}")
        return False


def test_4_full_production() -> bool:
    """Full production combination: structured + adaptive thinking + web_search."""
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Grant Road के पास अच्छा Chinese restaurant बताओ, "
                        "₹700 का budget है 4 लोगों के लिए।"
                    ),
                }
            ],
            tools=[
                {
                    "type": WEB_SEARCH_TOOL,
                    "name": "web_search",
                    "max_uses": 2,
                }
            ],
            extra_body={
                "output_config": {
                    "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}
                },
                "thinking": {"type": "adaptive"},
            },
        )
        parsed = _summarise(
            "4. full production (structured + thinking + web_search)", response
        )
        leaks = _check_cot_leak(parsed)
        if leaks:
            print(f"⚠️  CoT-leak markers in `out`: {leaks}")
        else:
            print("✓ no CoT-leak markers in `out`")
        return True
    except Exception as e:
        print(f"\n❌ TEST 4 FAILED: {e!r}")
        return False


def test_5_cot_leak_adversarial() -> bool:
    """Reasoning-heavy grievance prompt — does CoT bleed into `out`?

    The kind of prompt that, with a naive prompt-instructed JSON setup,
    would tempt the model to narrate its own deliberation. If structured
    output + thinking holds, `out` should be pure user-facing speech.
    """
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "मुझे समझ नहीं आ रहा — supervisor मुझे ज़्यादा काम देता है "
                        "पर salary बढ़ी नहीं तीन महीने से। दूसरों की बढ़ी है। "
                        "मुझे क्या करना चाहिए?"
                    ),
                }
            ],
            extra_body={
                "output_config": {
                    "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}
                },
                "thinking": {"type": "adaptive"},
            },
        )
        parsed = _summarise("5. adversarial CoT-leak probe", response)
        thinking_blocks = [
            b
            for b in response.content
            if getattr(b, "type", "") in ("thinking", "redacted_thinking")
        ]
        print(f"thinking blocks present: {len(thinking_blocks)}")
        leaks = _check_cot_leak(parsed)
        if leaks:
            print(f"⚠️  CoT-leak markers in `out`: {leaks}")
            return False
        print("✓ no CoT-leak markers in `out`")
        return True
    except Exception as e:
        print(f"\n❌ TEST 5 FAILED: {e!r}")
        return False


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("FATAL: ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 1

    print(f"Model        : {MODEL}")
    print(f"Anthropic SDK: {anthropic.__version__}")
    print(f"web_search   : {WEB_SEARCH_TOOL}")

    results: dict[str, bool] = {
        "1. plain output_config.format": test_1_plain(),
        "2. + adaptive thinking": test_2_with_thinking(),
        "3. + web_search (no thinking)": test_3_with_web_search(),
        "4. full production (thinking + web_search)": test_4_full_production(),
        "5. adversarial CoT-leak probe": test_5_cot_leak_adversarial(),
    }

    print(f"\n{'=' * 72}")
    print("SUMMARY")
    print(f"{'=' * 72}")
    for label, passed in results.items():
        mark = "✓" if passed else "✗"
        print(f"  {mark}  {label}")

    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
