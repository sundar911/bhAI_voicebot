"""
Tests for FAQCache: markdown loading, Jaccard matching,
threshold behaviour, and response formatting.

No external services required.
"""

import pytest


# ── Loading ───────────────────────────────────────────────────────────────

def test_load_entries_from_markdown(tmp_kb_dir):
    from src.bhai.resilience.faq_cache import FAQCache

    cache = FAQCache(tmp_kb_dir)
    assert len(cache.entries) >= 3


def test_entries_have_correct_domain(tmp_kb_dir):
    from src.bhai.resilience.faq_cache import FAQCache

    cache = FAQCache(tmp_kb_dir)
    domains = {e.domain for e in cache.entries}
    assert "hr_admin" in domains


def test_empty_kb_dir_returns_no_entries(tmp_path):
    from src.bhai.resilience.faq_cache import FAQCache

    empty = tmp_path / "empty_kb"
    empty.mkdir()
    cache = FAQCache(empty)
    assert cache.match("anything at all") is None


# ── Matching ──────────────────────────────────────────────────────────────

def test_exact_match_returns_entry(tmp_kb_dir):
    from src.bhai.resilience.faq_cache import FAQCache

    cache = FAQCache(tmp_kb_dir)
    result = cache.match("Salary kyun kata?")
    assert result is not None
    assert "salary" in result.question.lower()


def test_partial_match_within_threshold(tmp_kb_dir):
    from src.bhai.resilience.faq_cache import FAQCache

    cache = FAQCache(tmp_kb_dir, threshold=0.3)
    # "salary kyun kata" shares 3/4 tokens with FAQ question → Jaccard 0.75
    result = cache.match("salary kyun kata mere")
    assert result is not None


def test_unrelated_query_returns_none(tmp_kb_dir):
    from src.bhai.resilience.faq_cache import FAQCache

    cache = FAQCache(tmp_kb_dir, threshold=0.6)
    result = cache.match("Aaj mausam bahut sundar hai Mumbai mein")
    assert result is None


def test_threshold_high_blocks_partial_match(tmp_kb_dir):
    from src.bhai.resilience.faq_cache import FAQCache

    cache = FAQCache(tmp_kb_dir, threshold=0.95)
    # A close but not exact match should be blocked by a very high threshold
    result = cache.match("salary kata hua mere ko")
    assert result is None


def test_threshold_low_allows_partial_match(tmp_kb_dir):
    from src.bhai.resilience.faq_cache import FAQCache

    cache = FAQCache(tmp_kb_dir, threshold=0.1)
    result = cache.match("salary")
    assert result is not None


# ── Format Response ───────────────────────────────────────────────────────

def test_format_response_includes_answer(tmp_kb_dir):
    from src.bhai.resilience.faq_cache import FAQCache

    cache = FAQCache(tmp_kb_dir)
    entry = cache.entries[0]
    response = cache.format_response(entry)
    assert entry.answer in response


def test_format_response_includes_followup_prompt(tmp_kb_dir):
    from src.bhai.resilience.faq_cache import FAQCache

    cache = FAQCache(tmp_kb_dir)
    entry = cache.entries[0]
    response = cache.format_response(entry)
    assert "Aur kuch poochna hai?" in response


# ── Tokenizer and Jaccard Utilities ──────────────────────────────────────

def test_tokenize_strips_punctuation():
    from src.bhai.resilience.faq_cache import _tokenize

    tokens = _tokenize("Salary kyun kata? Tell me!")
    assert "?" not in tokens
    assert "!" not in tokens
    assert "salary" in tokens


def test_tokenize_filters_single_char_tokens():
    from src.bhai.resilience.faq_cache import _tokenize

    tokens = _tokenize("a b c longer")
    assert "a" not in tokens
    assert "b" not in tokens
    assert "longer" in tokens


def test_jaccard_similarity_identical_sets():
    from src.bhai.resilience.faq_cache import _jaccard_similarity

    s = {"salary", "kata", "kyun"}
    assert _jaccard_similarity(s, s) == 1.0


def test_jaccard_similarity_disjoint_sets():
    from src.bhai.resilience.faq_cache import _jaccard_similarity

    assert _jaccard_similarity({"a", "b"}, {"c", "d"}) == 0.0


def test_jaccard_similarity_partial_overlap():
    from src.bhai.resilience.faq_cache import _jaccard_similarity

    a = {"salary", "kyun", "kata"}
    b = {"salary", "kyun", "cut", "hua"}
    score = _jaccard_similarity(a, b)
    assert 0.0 < score < 1.0


def test_jaccard_similarity_empty_sets():
    from src.bhai.resilience.faq_cache import _jaccard_similarity

    assert _jaccard_similarity(set(), {"a"}) == 0.0
    assert _jaccard_similarity({"a"}, set()) == 0.0
