"""
Tests for src/bhai/llm/haiku_router.py — LLM-driven KB routing with
graceful fallback to the keyword router.

All tests mock the anthropic client; no real network calls.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bhai.llm.haiku_router import HaikuKBRouter, _read_title_and_keywords
from bhai.llm.kb_router import KBRouter


@pytest.fixture
def kb_with_helpdesk(tmp_path):
    """Synthetic KB with helpdesk/ containing _index + 3 files."""
    kb = tmp_path / "knowledge_base"
    helpdesk = kb / "helpdesk"
    helpdesk.mkdir(parents=True)

    (helpdesk / "_index.md").write_text(
        "# Helpdesk Topics\n\n- Aadhaar\n- PAN\n- Sukanya\n",
        encoding="utf-8",
    )
    (helpdesk / "aadhaar.md").write_text(
        "# Aadhaar Card\n\n"
        "## Keywords\n"
        "Aadhaar, UIDAI, e-Aadhaar, Seva Kendra\n\n"
        "## Common Questions\n",
        encoding="utf-8",
    )
    (helpdesk / "pan_card.md").write_text(
        "# PAN Card\n\n" "## Keywords\n" "PAN, e-PAN, NSDL, UTIITSL\n",
        encoding="utf-8",
    )
    (helpdesk / "scheme_sukanya_samriddhi.md").write_text(
        "# Sukanya Samriddhi\n\n" "## Keywords\n" "Sukanya, girl child savings, बेटी\n",
        encoding="utf-8",
    )
    return kb


def _make_response(text: str, cache_read: int = 0, cache_write: int = 0):
    """Build a mock anthropic response with a single text block."""
    block = SimpleNamespace(type="text", text=text)
    usage = SimpleNamespace(
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
    )
    return SimpleNamespace(content=[block], usage=usage)


def _make_client(response_text: str):
    """Build a mock anthropic client that returns a fixed response."""
    client = MagicMock()
    client.messages.create.return_value = _make_response(response_text)
    return client


def _make_router(kb_dir, response_text: str, *, fallback=None):
    """Construct a HaikuKBRouter with a mock client returning ``response_text``."""
    return HaikuKBRouter(
        kb_dir=kb_dir,
        fallback=fallback or KBRouter(kb_dir / "helpdesk"),
        api_key="test-key",
        client=_make_client(response_text),
    )


# ── _read_title_and_keywords ──────────────────────────────────────────


def test_read_title_and_keywords_combines_h1_and_first_keywords_line(tmp_path):
    f = tmp_path / "scheme_pmmy.md"
    f.write_text(
        "# Pradhan Mantri Mudra Yojana (PMMY)\n\n"
        "## Keywords\n"
        "Mudra, मुद्रा, business loan\n",
        encoding="utf-8",
    )
    desc = _read_title_and_keywords(f)
    assert "Pradhan Mantri Mudra Yojana" in desc
    assert "Mudra" in desc


def test_read_title_and_keywords_fallback_to_stem(tmp_path):
    f = tmp_path / "no_title.md"
    f.write_text("just some text\n", encoding="utf-8")
    assert _read_title_and_keywords(f) == "no_title"


# ── topic-list construction ───────────────────────────────────────────


def test_topic_list_includes_every_file_except_index(kb_with_helpdesk):
    router = _make_router(kb_with_helpdesk, "aadhaar")
    topic_list = router._build_topic_list()
    assert "aadhaar — Aadhaar Card" in topic_list
    assert "pan_card — PAN Card" in topic_list
    assert "scheme_sukanya_samriddhi — Sukanya Samriddhi" in topic_list
    assert "_index" not in topic_list


# ── route() — happy path ──────────────────────────────────────────────


def test_route_returns_index_plus_haiku_choice(kb_with_helpdesk):
    router = _make_router(kb_with_helpdesk, "KB: aadhaar\nUSE_CASES: scheme_kb")
    result = router.route("Aadhaar update kaise karu?")
    names = [p.name for p in result.paths]
    assert names == ["_index.md", "aadhaar.md"]
    assert result.use_cases == ["scheme_kb"]


def test_route_parses_comma_separated_output(kb_with_helpdesk):
    router = _make_router(
        kb_with_helpdesk, "KB: aadhaar, pan_card\nUSE_CASES: scheme_kb"
    )
    result = router.route("naam galat sab cards pe")
    names = [p.name for p in result.paths]
    assert names == ["_index.md", "aadhaar.md", "pan_card.md"]


def test_route_index_only_for_companion_query(kb_with_helpdesk):
    router = _make_router(kb_with_helpdesk, "KB: _index\nUSE_CASES:")
    result = router.route("आज मन भारी है")
    names = [p.name for p in result.paths]
    assert names == ["_index.md"]
    assert result.use_cases == []


def test_route_ignores_unknown_stems(kb_with_helpdesk):
    """Haiku might hallucinate a stem; the router drops unknown ones."""
    router = _make_router(
        kb_with_helpdesk, "KB: aadhaar, unknown_stem\nUSE_CASES: scheme_kb"
    )
    result = router.route("Aadhaar")
    names = [p.name for p in result.paths]
    assert names == ["_index.md", "aadhaar.md"]


def test_route_caps_at_top_n(kb_with_helpdesk):
    router = _make_router(
        kb_with_helpdesk,
        "KB: aadhaar, pan_card, scheme_sukanya_samriddhi\nUSE_CASES: scheme_kb",
    )
    result = router.route("everything please", top_n=1)
    # 1 index + 1 scored doc
    assert len(result.paths) == 2


def test_route_empty_transcript_returns_only_index(kb_with_helpdesk):
    router = _make_router(kb_with_helpdesk, "KB: _index\nUSE_CASES:")
    result = router.route("")
    names = [p.name for p in result.paths]
    assert names == ["_index.md"]
    assert result.use_cases == []
    # client should not even be called for empty transcripts
    router._client.messages.create.assert_not_called()


def test_route_uses_cache_control_in_system_prompt(kb_with_helpdesk):
    """The static prefix must be sent with cache_control so repeat calls cache."""
    router = _make_router(kb_with_helpdesk, "KB: aadhaar\nUSE_CASES: scheme_kb")
    router.route("Aadhaar update")
    call = router._client.messages.create.call_args
    system = call.kwargs["system"]
    assert isinstance(system, list)
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert "bhAI" in system[0]["text"]


# ── route() — fallback path ───────────────────────────────────────────


def test_route_falls_back_to_keyword_on_api_error(kb_with_helpdesk):
    """When the anthropic client raises, the keyword fallback runs."""
    fallback = KBRouter(kb_with_helpdesk / "helpdesk")
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("network down")
    router = HaikuKBRouter(
        kb_dir=kb_with_helpdesk,
        fallback=fallback,
        api_key="test-key",
        client=client,
    )
    result = router.route("Aadhaar update kaise karu?")
    names = [p.name for p in result.paths]
    # Keyword fallback should still hit aadhaar.md via filename stem
    assert "_index.md" in names
    assert "aadhaar.md" in names
    # Fallback never emits use-cases
    assert result.use_cases == []


def test_route_falls_back_on_empty_response(kb_with_helpdesk):
    """Empty model output → no scored docs, just _index."""
    router = _make_router(kb_with_helpdesk, "")
    result = router.route("some query")
    # No stems parsed → only index
    names = [p.name for p in result.paths]
    assert names == ["_index.md"]
    assert result.use_cases == []


def test_route_dedupes_repeated_stems(kb_with_helpdesk):
    """If Haiku returns the same stem twice, we don't double-inject."""
    router = _make_router(
        kb_with_helpdesk, "KB: aadhaar, aadhaar, aadhaar\nUSE_CASES: scheme_kb"
    )
    result = router.route("Aadhaar")
    names = [p.name for p in result.paths]
    assert names == ["_index.md", "aadhaar.md"]


# ── use-case parsing ──────────────────────────────────────────────────


def test_route_multi_label_use_cases(kb_with_helpdesk):
    """A turn can carry multiple use-case tags simultaneously."""
    router = _make_router(kb_with_helpdesk, "KB: _index\nUSE_CASES: grievance, finance")
    result = router.route("Salary nahi aayi, supervisor kuch bata nahi raha")
    assert result.use_cases == ["grievance", "finance"]


def test_route_filters_invalid_use_cases(kb_with_helpdesk):
    """Tags outside the allowlist are silently dropped."""
    router = _make_router(
        kb_with_helpdesk, "KB: _index\nUSE_CASES: grievance, bogus_tag, general"
    )
    result = router.route("anything")
    assert result.use_cases == ["grievance", "general"]


def test_route_dedupes_use_cases(kb_with_helpdesk):
    """Repeated tags are collapsed."""
    router = _make_router(
        kb_with_helpdesk, "KB: _index\nUSE_CASES: finance, finance, finance"
    )
    result = router.route("PF balance")
    assert result.use_cases == ["finance"]


def test_route_legacy_bare_stem_format_still_works(kb_with_helpdesk):
    """If the model slips and returns only a bare stem line (old format),
    treat it as the KB line and leave use-cases empty."""
    router = _make_router(kb_with_helpdesk, "aadhaar")
    result = router.route("Aadhaar update")
    names = [p.name for p in result.paths]
    assert names == ["_index.md", "aadhaar.md"]
    assert result.use_cases == []


def test_route_handles_case_insensitive_labels(kb_with_helpdesk):
    """Labels are case-insensitive on parse (model may capitalise)."""
    router = _make_router(kb_with_helpdesk, "kb: aadhaar\nuse_cases: GRIEVANCE")
    result = router.route("anything")
    names = [p.name for p in result.paths]
    assert "aadhaar.md" in names
    assert result.use_cases == ["grievance"]
