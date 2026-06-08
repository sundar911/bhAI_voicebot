"""Tests for the v2 open-threads pipeline.

Piece A of the open-threads architecture: the reactive LLM emits
`<thread>` blocks alongside `<memory>` blocks; ``BaseLLM`` parses them
into ``ThreadPatch`` objects and strips them before the response goes
to TTS. Persistence (piece B) and dossier rendering (piece C) land in
follow-up commits.
"""

from __future__ import annotations

from bhai.llm.base import BaseLLM
from bhai.proactive.threads import SLUG_PATTERN, THREAD_OPS, ThreadPatch

# ── ThreadPatch validation ─────────────────────────────────────────────


def test_thread_patch_open_valid():
    p = ThreadPatch(op="open", topic="saree_business_expansion", context="₹1L loan")
    assert p.is_valid()


def test_thread_patch_close_valid():
    p = ThreadPatch(op="close", topic="saree_business_expansion", context="resolved")
    assert p.is_valid()


def test_thread_patch_mark_sensitive_valid_with_empty_context():
    """mark_sensitive is the one op where context is optional — it's a flag."""
    p = ThreadPatch(op="mark_sensitive", topic="daughter_recovery", context="")
    assert p.is_valid()


def test_thread_patch_invalid_op():
    p = ThreadPatch(op="delete", topic="foo", context="bar")
    assert not p.is_valid()


def test_thread_patch_invalid_slug_with_hyphen():
    """Hyphens are intentionally excluded from slugs — see threads.py."""
    p = ThreadPatch(op="open", topic="saree-business", context="x")
    assert not p.is_valid()


def test_thread_patch_invalid_slug_with_space():
    p = ThreadPatch(op="open", topic="saree business", context="x")
    assert not p.is_valid()


def test_thread_patch_invalid_open_missing_context():
    p = ThreadPatch(op="open", topic="saree_business_expansion", context="")
    assert not p.is_valid()


def test_thread_ops_constant_covers_all_documented_ops():
    """Guardrail: if the documented ops in THREAD_INSTRUCTION drift from
    the THREAD_OPS allowlist, the parser will silently start dropping
    new ops as 'unknown' — keep the two in lockstep."""
    assert set(THREAD_OPS) == {"open", "update", "close", "mark_sensitive"}


def test_slug_pattern_accepts_underscores_digits_lowercase():
    assert SLUG_PATTERN.match("saree_business_2026")
    assert not SLUG_PATTERN.match("Saree_Business")  # case-sensitive
    assert not SLUG_PATTERN.match("")  # empty
    assert not SLUG_PATTERN.match("a" * 81)  # too long


# ── _strip_thread_patches ──────────────────────────────────────────────


def test_strip_thread_patches_removes_single_block():
    raw = (
        "मणीमाला जी, समझ गई। बस ₹8000 EMI थोड़ा tight लगेगा। "
        "<thread>open: saree_business_expansion / ₹1L loan plan for Surat supplier diversification</thread>"
    )
    cleaned = BaseLLM._strip_thread_patches(raw)
    assert "<thread>" not in cleaned
    assert "open:" not in cleaned
    assert "₹8000 EMI" in cleaned


def test_strip_thread_patches_removes_multiple_blocks():
    raw = (
        "ठीक है। <thread>open: a / one</thread> "
        "<thread>update: b / two</thread> "
        "<thread>mark_sensitive: c</thread>"
    )
    cleaned = BaseLLM._strip_thread_patches(raw)
    assert "<thread>" not in cleaned
    assert "ठीक है।" in cleaned


def test_strip_thread_patches_idempotent_on_clean_text():
    raw = "नमस्ते, सब ठीक है ना?"
    assert BaseLLM._strip_thread_patches(raw) == raw


def test_strip_thread_patches_case_insensitive_tag():
    raw = "ठीक <THREAD>open: x / hello</THREAD> done."
    cleaned = BaseLLM._strip_thread_patches(raw)
    assert "<thread>" not in cleaned.lower()
    assert "open:" not in cleaned


def test_strip_thread_patches_handles_multiline_context():
    """DOTALL — open/update context can span multiple lines."""
    raw = (
        "ठीक है।\n"
        "<thread>open: x / line one\n"
        "line two\n"
        "line three</thread>\n"
        "और कुछ बात?"
    )
    cleaned = BaseLLM._strip_thread_patches(raw)
    assert "<thread>" not in cleaned
    assert "line one" not in cleaned
    assert "और कुछ बात?" in cleaned


# ── _parse_thread_patches ──────────────────────────────────────────────


def test_parse_thread_patches_open():
    raw = (
        "<thread>open: saree_business_expansion / Manimala mentioned ₹1L loan</thread>"
    )
    patches = BaseLLM._parse_thread_patches(raw)
    assert patches is not None
    assert len(patches) == 1
    p = patches[0]
    assert p.op == "open"
    assert p.topic == "saree_business_expansion"
    assert "Manimala mentioned" in p.context


def test_parse_thread_patches_update():
    raw = (
        "<thread>update: saree_business_expansion / "
        "Decided not to take loan after the EMI math</thread>"
    )
    patches = BaseLLM._parse_thread_patches(raw)
    assert patches is not None
    assert patches[0].op == "update"
    assert "Decided not to take loan" in patches[0].context


def test_parse_thread_patches_close():
    raw = (
        "<thread>close: saree_business_expansion / "
        "User went to Surat and bought 3-month inventory; resolved</thread>"
    )
    patches = BaseLLM._parse_thread_patches(raw)
    assert patches is not None
    assert patches[0].op == "close"


def test_parse_thread_patches_mark_sensitive_no_context():
    raw = "<thread>mark_sensitive: daughter_recovery</thread>"
    patches = BaseLLM._parse_thread_patches(raw)
    assert patches is not None
    assert patches[0].op == "mark_sensitive"
    assert patches[0].topic == "daughter_recovery"
    assert patches[0].context == ""


def test_parse_thread_patches_returns_none_when_absent():
    assert BaseLLM._parse_thread_patches("just a normal reply") is None
    assert BaseLLM._parse_thread_patches("") is None


def test_parse_thread_patches_preserves_emission_order():
    raw = (
        "<thread>open: a / first</thread>"
        "<thread>open: b / second</thread>"
        "<thread>open: c / third</thread>"
    )
    patches = BaseLLM._parse_thread_patches(raw)
    assert patches is not None
    assert [p.topic for p in patches] == ["a", "b", "c"]


def test_parse_thread_patches_drops_unknown_op():
    """Unknown ops (e.g. 'delete') are logged and skipped, not coerced."""
    raw = (
        "<thread>delete: saree_business_expansion / drop me</thread>"
        "<thread>open: real_thread / kept</thread>"
    )
    patches = BaseLLM._parse_thread_patches(raw)
    assert patches is not None
    assert len(patches) == 1
    assert patches[0].topic == "real_thread"


def test_parse_thread_patches_drops_bad_slug():
    """Hyphenated slugs are invalid; the parser drops the patch."""
    raw = "<thread>open: saree-business / bad slug</thread>"
    patches = BaseLLM._parse_thread_patches(raw)
    assert patches is None


def test_parse_thread_patches_drops_missing_separator():
    """open/update/close need ' / ' between slug and context."""
    raw = "<thread>open: missing_slash_separator</thread>"
    patches = BaseLLM._parse_thread_patches(raw)
    assert patches is None


def test_parse_thread_patches_drops_empty_open_context():
    """An open op without context is malformed — drop it."""
    raw = "<thread>open: foo / </thread>"
    patches = BaseLLM._parse_thread_patches(raw)
    assert patches is None


def test_parse_thread_patches_mixed_with_memory_blocks():
    """Threads coexist with memory blocks in the same response — each is
    parsed by its own parser, neither contaminates the other."""
    raw = (
        "अरे ठीक है।"
        "<memory>fact: planning ₹1L loan</memory>"
        "<thread>open: saree_business_expansion / ₹1L loan for Surat</thread>"
        "<memory>fact: work_location: BC</memory>"
    )
    threads = BaseLLM._parse_thread_patches(raw)
    memory = BaseLLM._parse_memory_patches(raw)
    assert threads is not None and len(threads) == 1
    assert memory is not None
    assert "planning ₹1L loan" in memory["facts"]
    assert threads[0].topic == "saree_business_expansion"


# ── clean_response strips thread blocks alongside memory ───────────────


def test_clean_response_strips_thread_blocks_before_tts():
    raw = (
        "अरे, समझ गई।\n"
        "<memory>fact: planning Surat trip</memory>\n"
        "<thread>open: surat_diwali_trip / planning Diwali Surat trip for new inventory</thread>"
    )
    cleaned = BaseLLM._clean_response(raw)
    assert "<thread>" not in cleaned
    assert "<memory>" not in cleaned
    assert "fact:" not in cleaned
    assert "open:" not in cleaned
    assert "समझ गई" in cleaned
