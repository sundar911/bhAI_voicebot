"""
Tests for src/bhai/resilience/faq_cache.py — tokenization, Jaccard similarity,
and knowledge-base FAQ matching.
"""

import pytest

from bhai.resilience.faq_cache import (
    FAQCache,
    FAQEntry,
    _jaccard_similarity,
    _tokenize,
)

# ── Unit tests for pure functions ─────────────────────────────────────


def test_tokenize_basic():
    """Splits on whitespace, lowercases, filters single-char tokens."""
    tokens = _tokenize("Salary kyun kata?")
    assert "salary" in tokens
    assert "kyun" in tokens
    assert "kata" in tokens
    # single chars filtered
    assert "?" not in tokens


def test_tokenize_hindi():
    """Handles Devanagari text."""
    tokens = _tokenize("मेरी salary कब आएगी")
    assert "मेरी" in tokens
    assert "salary" in tokens
    assert "कब" in tokens
    assert "आएगी" in tokens


def test_tokenize_strips_punctuation():
    """Arrow and quote characters are stripped."""
    tokens = _tokenize('→ "Salary kyun kata?"')
    assert "salary" in tokens
    assert "→" not in tokens
    assert '"' not in tokens


def test_jaccard_identical():
    """Identical sets → similarity 1.0."""
    s = {"a", "b", "c"}
    assert _jaccard_similarity(s, s) == 1.0


def test_jaccard_disjoint():
    """Completely different sets → similarity 0.0."""
    assert _jaccard_similarity({"a", "b"}, {"c", "d"}) == 0.0


def test_jaccard_partial():
    """Partial overlap is between 0 and 1."""
    score = _jaccard_similarity({"a", "b", "c"}, {"b", "c", "d"})
    # intersection=2, union=4 → 0.5
    assert score == pytest.approx(0.5)


def test_jaccard_empty():
    """Empty set always returns 0.0."""
    assert _jaccard_similarity(set(), {"a"}) == 0.0
    assert _jaccard_similarity({"a"}, set()) == 0.0


# ── FAQCache tests ─────────────────────────────────────────────────────


@pytest.fixture
def kb_with_faqs(tmp_path):
    """Knowledge base directory with a FAQ section in hr_admin/payroll.md."""
    kb = tmp_path / "knowledge_base"
    hr = kb / "hr_admin"
    hr.mkdir(parents=True)

    (hr / "payroll.md").write_text(
        "## Payroll Information\n\n"
        "Salaries are paid on the 5th of every month.\n\n"
        "## Common Questions\n\n"
        '### "Salary kyun kata?"\n'
        "→ Salary kat sakti hai absence, late coming, ya loan EMI ki wajah se.\n\n"
        '### "PF kab milega?"\n'
        "→ PF withdrawal ke liye HR se form lo. Processing mein 30 din lagte hain.\n\n",
        encoding="utf-8",
    )
    return kb


def test_empty_cache_no_match(tmp_path):
    """FAQCache with no KB files returns None for any query."""
    cache = FAQCache(tmp_path / "empty_kb")
    assert cache.match("salary kyun kata") is None


def test_match_returns_best_entry(kb_with_faqs):
    """High-similarity query hits the correct FAQ entry."""
    cache = FAQCache(kb_with_faqs, threshold=0.3)
    result = cache.match("salary kyun kata")
    assert result is not None
    assert "salary" in result.question.lower() or "salary" in result.answer.lower()


def test_no_match_below_threshold(kb_with_faqs):
    """Unrelated query returns None when below threshold."""
    cache = FAQCache(kb_with_faqs, threshold=0.9)
    result = cache.match("train ka schedule kya hai")
    assert result is None


def test_format_response_includes_followup(kb_with_faqs):
    """format_response wraps the answer with a follow-up prompt."""
    cache = FAQCache(kb_with_faqs, threshold=0.3)
    entry = cache.match("salary kyun kata")
    assert entry is not None
    response = cache.format_response(entry)
    assert "Aur kuch poochna hai?" in response
    assert entry.answer in response


def test_cache_ignores_shared_and_users_dirs(tmp_path):
    """Shared and users subdirectories are not parsed for FAQ entries."""
    kb = tmp_path / "knowledge_base"
    shared = kb / "shared"
    shared.mkdir(parents=True)

    (shared / "style_guide.md").write_text(
        "## Common Questions\n\n"
        '### "Should this be indexed?"\n'
        "→ No, shared files are ignored.\n\n",
        encoding="utf-8",
    )

    cache = FAQCache(kb)
    # Even a perfect match should not appear (shared/ is excluded)
    assert cache.match("should this be indexed") is None
