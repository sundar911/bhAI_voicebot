"""
Tests for src/bhai/llm/kb_router.py — keyword-based document selection
for system-prompt injection.
"""

import pytest

from bhai.llm.kb_router import KBRouter, _profile_tokens


@pytest.fixture
def helpdesk_kb(tmp_path):
    """Synthetic helpdesk dir with an index + a few topical files."""
    helpdesk = tmp_path / "helpdesk"
    helpdesk.mkdir()

    (helpdesk / "_index.md").write_text(
        "# bhAI Helpdesk Topics\n\n"
        "- Aadhaar — update, fees, centres\n"
        "- PAN card — apply, link to Aadhaar\n"
        "- Sukanya Samriddhi — girl child savings\n",
        encoding="utf-8",
    )
    (helpdesk / "aadhaar.md").write_text(
        "# Aadhaar Card\n\n"
        "## Common Questions\n\n"
        '### "How to update Aadhaar?"\n'
        "→ Visit a Seva Kendra.\n",
        encoding="utf-8",
    )
    (helpdesk / "pan_card.md").write_text(
        "# PAN Card\n\n"
        "## Keywords\n"
        "PAN, income tax, e-PAN, NSDL, UTIITSL\n\n"
        "## Common Questions\n\n"
        '### "How to apply for PAN?"\n'
        "→ Apply online at NSDL.\n",
        encoding="utf-8",
    )
    (helpdesk / "scheme_sukanya_samriddhi.md").write_text(
        "# Sukanya Samriddhi Yojana\n\n"
        "## Keywords\n"
        "Sukanya, Samriddhi, girl child, बेटी, savings, SSY\n\n"
        "Savings scheme for girl children.\n",
        encoding="utf-8",
    )
    return helpdesk


def test_profile_tokens_filename_split(tmp_path):
    """Filename underscores are split into tokens (both all and stem sets)."""
    f = tmp_path / "marriage_certificate.md"
    f.write_text("# Marriage Certificate\n", encoding="utf-8")
    profile = _profile_tokens(f)
    assert "marriage" in profile.all_tokens
    assert "certificate" in profile.all_tokens
    assert profile.stem_tokens == {"marriage", "certificate"}


def test_profile_tokens_picks_up_keywords_block(tmp_path):
    """Explicit ## Keywords block contributes tokens to all_tokens (not stem)."""
    f = tmp_path / "scheme_pmmy.md"
    f.write_text(
        "# PMMY\n\n"
        "## Keywords\n"
        "Mudra, मुद्रा, business loan, छोटा loan\n\n"
        "## Eligibility\nFoo bar.\n",
        encoding="utf-8",
    )
    profile = _profile_tokens(f)
    assert "mudra" in profile.all_tokens
    assert "मुद्रा" in profile.all_tokens
    assert "loan" in profile.all_tokens
    assert "छोटा" in profile.all_tokens
    # stem_tokens only carries what comes from the filename
    assert profile.stem_tokens == {"scheme", "pmmy"}


def test_router_always_includes_index(helpdesk_kb):
    """Index file is included even when transcript is empty or unrelated."""
    router = KBRouter(helpdesk_kb)
    result = router.route("")
    assert result == [helpdesk_kb / "_index.md"]

    result = router.route("तू कैसा है")
    assert result == [helpdesk_kb / "_index.md"]


def test_router_matches_aadhaar_query(helpdesk_kb):
    """Query about Aadhaar returns aadhaar.md alongside index."""
    router = KBRouter(helpdesk_kb)
    result = router.route("Aadhaar update kaise karu")
    names = [p.name for p in result]
    assert "_index.md" in names
    assert "aadhaar.md" in names


def test_router_matches_via_keywords_block(helpdesk_kb):
    """Sukanya scheme is matched even though filename starts with 'scheme_'."""
    router = KBRouter(helpdesk_kb)
    result = router.route("Sukanya yojana eligibility क्या है")
    names = [p.name for p in result]
    assert "scheme_sukanya_samriddhi.md" in names


def test_router_respects_top_n(helpdesk_kb):
    """top_n caps the number of scored docs returned (excluding index)."""
    router = KBRouter(helpdesk_kb)
    # Query that touches multiple docs
    result = router.route("Aadhaar PAN Sukanya", top_n=1, threshold=0.0)
    # 1 index + 1 scored doc = 2 entries max
    assert len(result) == 2
    assert result[0].name == "_index.md"


def test_router_threshold_filters_weak_matches(helpdesk_kb):
    """Off-topic query with no token overlap routes to index only."""
    router = KBRouter(helpdesk_kb)
    result = router.route("monsoon mein train ki bhid")
    assert result == [helpdesk_kb / "_index.md"]


def test_router_score_prefers_filename_stem(helpdesk_kb):
    """The bare token 'aadhaar' routes to aadhaar.md, not pan_card.md.

    Even though pan_card.md mentions Aadhaar in passing (e-KYC), the
    stem-bonus tie-breaks toward the file *named* aadhaar.
    """
    router = KBRouter(helpdesk_kb)
    result = router.route("Aadhaar")
    names = [p.name for p in result]
    # aadhaar.md must be present; pan_card.md may or may not, but if
    # both score, aadhaar.md must rank first among scored docs.
    assert "aadhaar.md" in names
    scored_names = [n for n in names if n != "_index.md"]
    assert scored_names[0] == "aadhaar.md"


def test_router_handles_missing_dir(tmp_path):
    """Non-existent directory yields a router that returns empty list."""
    router = KBRouter(tmp_path / "does_not_exist")
    assert router.route("anything") == []


def test_router_without_index(tmp_path):
    """Domain dir with files but no _index.md still routes scored docs."""
    helpdesk = tmp_path / "helpdesk"
    helpdesk.mkdir()
    (helpdesk / "voter_id.md").write_text(
        "# Voter ID\n\n## Keywords\nvoter, EPIC, election\n",
        encoding="utf-8",
    )
    router = KBRouter(helpdesk)
    result = router.route("voter ID kaise milega")
    assert result == [helpdesk / "voter_id.md"]
