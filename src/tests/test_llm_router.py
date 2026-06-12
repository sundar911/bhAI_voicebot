"""
Tests for src/bhai/llm/llm_router.py — LLM-driven KB + use-case routing
(Sonnet 4.6) with graceful fallback to the keyword router.

All tests mock the anthropic client; no real network calls.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bhai.llm.kb_router import KBRouter
from bhai.llm.llm_router import LLMKBRouter, _read_title_and_keywords


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
    """Construct an LLMKBRouter with a mock client returning ``response_text``."""
    return LLMKBRouter(
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
    router = LLMKBRouter(
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
    router = _make_router(
        kb_with_helpdesk, "KB: _index\nUSE_CASES: grievance, finance_advice"
    )
    result = router.route("Supervisor se jhagda, aur loan le lu kya")
    assert result.use_cases == ["grievance", "finance_advice"]


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
        kb_with_helpdesk, "KB: _index\nUSE_CASES: general, general, general"
    )
    result = router.route("kuch bhi")
    assert result.use_cases == ["general"]


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


def test_route_finance_advice_tag_recognised(kb_with_helpdesk):
    """finance_advice is in the allowlist (covers loan/EMI decisions)."""
    router = _make_router(kb_with_helpdesk, "KB: _index\nUSE_CASES: finance_advice")
    result = router.route("₹1 lakh ka loan le rahi hu, EMI ₹8000")
    assert result.use_cases == ["finance_advice"]


# ── conversation_history context ──────────────────────────────────────


def test_route_no_history_sends_only_current_turn(kb_with_helpdesk):
    """With no history, the API message says `Current: <transcript>` only."""
    router = _make_router(kb_with_helpdesk, "KB: aadhaar\nUSE_CASES: scheme_kb")
    router.route("Aadhaar update")
    call = router._client.messages.create.call_args
    msgs = call.kwargs["messages"]
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "Current: Aadhaar update"
    assert "Prior:" not in msgs[0]["content"]


def test_route_with_history_includes_prior_turns_in_user_message(kb_with_helpdesk):
    """Conversation history is rendered into the single user message as a
    `Prior: ... Current: ...` block."""
    router = _make_router(kb_with_helpdesk, "KB: _index\nUSE_CASES: scheme_kb")
    history = [
        {"role": "user", "content": "दोनों बच्चों का आधार बनवाना है"},
        {"role": "assistant", "content": "BC centre जाना होगा"},
    ]
    router.route("बस इतना ही?", conversation_history=history)
    call = router._client.messages.create.call_args
    msg = call.kwargs["messages"][0]["content"]
    assert "Prior:" in msg
    assert "User: दोनों बच्चों का आधार बनवाना है" in msg
    assert "bhAI: BC centre जाना होगा" in msg
    assert "Current: बस इतना ही?" in msg


def test_route_truncates_long_history_to_last_context_turns(kb_with_helpdesk):
    """Only the last DEFAULT_CONTEXT_TURNS messages are included."""
    from bhai.llm.llm_router import DEFAULT_CONTEXT_TURNS

    router = _make_router(kb_with_helpdesk, "KB: _index\nUSE_CASES:")
    # Build a long history; older messages should be dropped.
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg-{i}"}
        for i in range(20)
    ]
    router.route("कुछ नया?", conversation_history=history)
    msg = router._client.messages.create.call_args.kwargs["messages"][0]["content"]
    # The oldest message must not be in the prompt
    assert "msg-0" not in msg
    # The last DEFAULT_CONTEXT_TURNS messages MUST be in the prompt
    for i in range(20 - DEFAULT_CONTEXT_TURNS, 20):
        assert f"msg-{i}" in msg


def test_route_skips_empty_history_messages(kb_with_helpdesk):
    """Blank content in history doesn't produce empty lines in the prompt."""
    router = _make_router(kb_with_helpdesk, "KB: _index\nUSE_CASES:")
    history = [
        {"role": "user", "content": ""},
        {"role": "assistant", "content": "  "},
        {"role": "user", "content": "real message"},
    ]
    router.route("follow-up", conversation_history=history)
    msg = router._client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "User: real message" in msg
    # No "User: " line with empty content
    assert "User: \n" not in msg
    assert "bhAI: \n" not in msg


def test_route_history_logged_with_ctx_msgs_count(kb_with_helpdesk, caplog):
    """The decision log line shows how many context messages were sent."""
    import logging

    caplog.set_level(logging.INFO, logger="bhai.llm.llm_router")
    router = _make_router(kb_with_helpdesk, "KB: aadhaar\nUSE_CASES: scheme_kb")
    history = [
        {"role": "user", "content": "previous question"},
        {"role": "assistant", "content": "previous answer"},
    ]
    router.route("follow-up", conversation_history=history)
    # ctx_msgs counts the rendered prior turns sent in the single user message
    log_lines = [r.getMessage() for r in caplog.records]
    assert any("llm_router decision" in l for l in log_lines)
