"""Tests for src/bhai/llm/claude_llm.py — web_search wiring.

We mock the anthropic.Anthropic client so the tests don't burn API quota
or need network. The assertions are about the *shape* of the call we make
to messages.create — does it include `tools=...` when the flag is on,
does it omit `tools` when off, and does it concatenate multiple TextBlocks
from the response correctly (the response shape Anthropic produces when
the model uses web_search server-side and emits interleaved text +
tool-use + tool-result blocks).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bhai.config import load_config
from bhai.llm.claude_llm import ClaudeLLM


def _cfg(**overrides):
    cfg = load_config()
    cfg.anthropic_api_key = "fake-key-for-tests"
    cfg.llm_backend = "claude"
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _mock_client(text_blocks: list[str], stop_reason: str = "end_turn"):
    """Build a fake anthropic.Anthropic client whose messages.create
    returns a response whose content has the given text blocks (in
    order). Used to verify multi-block concatenation and call args."""
    from anthropic.types import TextBlock

    content = [TextBlock(citations=None, text=t, type="text") for t in text_blocks]
    response = SimpleNamespace(content=content, stop_reason=stop_reason)
    client = MagicMock()
    client.messages.create.return_value = response
    return client


# ── flag off → no tools passed (back-compat) ─────────────────────────


def test_call_api_omits_tools_when_flag_off(tmp_knowledge_base):
    cfg = _cfg(web_search_enabled=False)
    llm = ClaudeLLM(cfg, knowledge_base_dir=tmp_knowledge_base)
    llm.client = _mock_client(["bare response, no tools"])

    out = llm._call_api("system", "user")

    assert out == "bare response, no tools"
    call = llm.client.messages.create.call_args
    assert "tools" not in call.kwargs


# ── flag on → tools passed with the configured shape ────────────────


def test_call_api_passes_web_search_tool_when_flag_on(tmp_knowledge_base):
    cfg = _cfg(
        web_search_enabled=True,
        web_search_max_uses_per_call=3,
        web_search_tool_name="web_search_20250305",
    )
    llm = ClaudeLLM(cfg, knowledge_base_dir=tmp_knowledge_base)
    llm.client = _mock_client(["grounded answer"])

    llm._call_api("system", "user")

    call = llm.client.messages.create.call_args
    tools = call.kwargs.get("tools")
    assert tools == [
        {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 3,
        }
    ]


def test_call_api_respects_configured_max_uses_and_tool_name(tmp_knowledge_base):
    """When the operator overrides via env, the tool spec reflects it —
    important so the integration can roll forward as Anthropic versions
    the web_search type identifier."""
    cfg = _cfg(
        web_search_enabled=True,
        web_search_max_uses_per_call=5,
        web_search_tool_name="web_search_20260101",
    )
    llm = ClaudeLLM(cfg, knowledge_base_dir=tmp_knowledge_base)
    llm.client = _mock_client(["x"])

    llm._call_api("system", "user")

    tools = llm.client.messages.create.call_args.kwargs["tools"]
    assert tools[0]["type"] == "web_search_20260101"
    assert tools[0]["max_uses"] == 5


# ── response shape — concat all TextBlocks ─────────────────────────


def test_call_api_concatenates_multiple_text_blocks(tmp_knowledge_base):
    """When web_search fires, Anthropic emits interleaved text +
    server_tool_use + web_search_tool_result blocks. The text answer
    typically lands across multiple TextBlocks (one before the search,
    one after). Grabbing only the first drops the actual answer."""
    cfg = _cfg(web_search_enabled=True)
    llm = ClaudeLLM(cfg, knowledge_base_dir=tmp_knowledge_base)
    # Pre-search reasoning + the actual answer after seeing search results.
    llm.client = _mock_client(
        [
            "Let me check Bandra box cricket venues.",
            "Cricket Hub Khar में box cricket है, ₹1500-2000 per hour के around।",
        ]
    )

    out = llm._call_api("system", "user")

    # Both text segments survive concatenation in order.
    assert "Let me check" in out
    assert "Cricket Hub Khar" in out
    # And the newline join keeps them as separate paragraphs.
    assert "\n" in out


def test_call_api_handles_empty_text_blocks(tmp_knowledge_base):
    """If the response had only tool-use/result blocks and no text, we
    return an empty string (the higher-level retry path treats this as a
    failure and falls back safely)."""
    cfg = _cfg(web_search_enabled=True)
    llm = ClaudeLLM(cfg, knowledge_base_dir=tmp_knowledge_base)
    llm.client = _mock_client([])  # no text blocks at all

    assert llm._call_api("system", "user") == ""


def test_call_api_strips_surrounding_whitespace(tmp_knowledge_base):
    cfg = _cfg(web_search_enabled=False)
    llm = ClaudeLLM(cfg, knowledge_base_dir=tmp_knowledge_base)
    llm.client = _mock_client(["   leading and trailing whitespace   "])

    assert llm._call_api("system", "user") == "leading and trailing whitespace"
