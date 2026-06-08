"""Tests for src/bhai/proactive/thinker.py — the ProactiveThinker agent loop.

The Anthropic client and tool runner are both dependency-injected, so
tests construct fakes that return canned responses for each pass. This
lets us validate the loop structure (brainstorm → critique → tools →
draft → judge) without burning real API quota.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from src.bhai.config import Config
from src.bhai.proactive.agent_input import AgentInput
from src.bhai.proactive.dossier_loader import UserDossier
from src.bhai.proactive.thinker import (
    BrainstormCandidate,
    ProactiveThinker,
    _parse_json_response,
)
from src.bhai.proactive.tools._types import ToolResult

# ── _parse_json_response ──────────────────────────────────────────────


class TestParseJsonResponse:
    def test_clean_json(self):
        assert _parse_json_response('{"foo": 1}') == {"foo": 1}

    def test_fence_wrapped(self):
        raw = '```json\n{"foo": 2}\n```'
        assert _parse_json_response(raw) == {"foo": 2}

    def test_unlabeled_fence(self):
        raw = '```\n{"foo": 3}\n```'
        assert _parse_json_response(raw) == {"foo": 3}

    def test_prose_around_json(self):
        raw = 'Here is your output: {"foo": 4} that\'s it.'
        assert _parse_json_response(raw) == {"foo": 4}

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            _parse_json_response("not json at all")


# ── Fakes ─────────────────────────────────────────────────────────────


class FakeAnthropic:
    """Returns canned responses per call. Use `set_responses(...)` to script
    the brainstorm → critique → draft → judge sequence."""

    def __init__(self):
        self.responses: List[str] = []
        self.calls: List[Dict[str, Any]] = []

    def set_responses(self, responses: List[str]):
        self.responses = list(responses)

    def messages_create(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: List[Dict[str, str]],
        temperature: float,
    ) -> str:
        self.calls.append(
            {
                "model": model,
                "system": system,
                "messages": messages,
                "temperature": temperature,
            }
        )
        if not self.responses:
            raise RuntimeError("FakeAnthropic ran out of canned responses")
        return self.responses.pop(0)


class FakeToolRunner:
    """Returns canned tool results indexed by tool name."""

    def __init__(self):
        self.canned: Dict[str, ToolResult] = {}
        self.calls: List[Dict[str, Any]] = []

    def set(self, tool_name: str, result: ToolResult):
        self.canned[tool_name] = result

    def run(self, tool_name, brief, agent_input):
        self.calls.append({"tool": tool_name, "brief": brief})
        return self.canned.get(
            tool_name,
            ToolResult(ok=False, tool=tool_name, error="not_canned"),
        )


def _agent_input(name: str = "Manimala") -> AgentInput:
    d = UserDossier(
        phone=f"tg_{name.lower()}",
        phone_hash="abc123def456",
        summary="Test user summary.",
        core_facts=[f"Naam: {name}", "Saree wholesale business"],
        family_facts=["beti exam de rahi hai"],
    )
    return AgentInput(
        dossier=d,
        recent_messages=[
            {"role": "user", "content": "kaise ho?", "timestamp": "2026-06-02"},
            {
                "role": "assistant",
                "content": "main theek hoon",
                "timestamp": "2026-06-02",
            },
        ],
    )


def _thinker(anthropic: FakeAnthropic, tools: FakeToolRunner) -> ProactiveThinker:
    cfg = Config()
    return ProactiveThinker(
        cfg,
        anthropic_caller=anthropic,
        tool_runner=tools,
        model="claude-sonnet-4-6",
    )


# ── Substantive loop — happy path ────────────────────────────────────


def _brainstorm_canned(n: int = 3) -> str:
    return json.dumps(
        {
            "candidates": [
                {
                    "category": "substantive",
                    "summary": f"Check in on saree business {i}",
                    "trace": "core_facts: Saree wholesale business",
                    "tools_needed": [],
                    "why_now": "user mentioned business growth",
                }
                for i in range(n)
            ]
        }
    )


def _critique_canned(chosen_index: int = 0) -> str:
    return json.dumps(
        {
            "chosen_index": chosen_index,
            "verdicts": [
                {
                    "index": 0,
                    "passes": ["off-target", "tool-privacy"],
                    "fails": [],
                    "reasoning": "ok",
                }
            ],
            "silent_day_reason": None,
        }
    )


def _judge_canned(verdict: str = "pass") -> str:
    return json.dumps(
        {
            "verdict": verdict,
            "checks": {
                "relentless": "pass",
                "creepy": "pass",
                "off_target": "pass",
                "privacy_leak": "pass",
            },
            "reasoning": "" if verdict == "pass" else "tripped a check",
        }
    )


class TestThinkSubstantiveHappyPath:
    def test_no_tools_full_loop(self):
        anth = FakeAnthropic()
        anth.set_responses(
            [
                _brainstorm_canned(3),
                _critique_canned(0),
                "अरे मणीमाला, कैसी हो आज? कल आपके saree business के बारे में सोच रही थी।",
                _judge_canned("pass"),
            ]
        )
        tools = FakeToolRunner()
        t = _thinker(anth, tools)
        result = t.think_substantive(_agent_input(), slot="morning")

        assert result.slot == "morning"
        assert result.category == "substantive"
        assert result.text is not None
        assert "मणीमाला" in result.text
        assert result.silent_day_reason is None
        assert len(result.brainstorm_candidates) == 3
        assert result.judge_verdict is not None
        assert result.judge_verdict["verdict"] == "pass"
        # No tools needed → tool_runner not called.
        assert tools.calls == []
        # 4 Anthropic calls: brainstorm, critique, draft, judge.
        assert len(anth.calls) == 4

    def test_with_nanobanana_tool(self, tmp_path: Path):
        bs = json.dumps(
            {
                "candidates": [
                    {
                        "category": "artifact",
                        "summary": "Logo for saree wholesale, warm earthy palette",
                        "trace": "core_facts: Saree wholesale business",
                        "tools_needed": ["nanobanana"],
                        "why_now": "demonstrate AI capability",
                    }
                ]
            }
        )
        anth = FakeAnthropic()
        anth.set_responses(
            [
                bs,
                _critique_canned(0),
                "अरे, ek logo design karke dekha — bhej rahi hoon, kaisa laga?",
                _judge_canned("pass"),
            ]
        )
        tools = FakeToolRunner()
        artifact = tmp_path / "logo.png"
        artifact.write_bytes(b"FAKE_PNG")
        tools.set(
            "nanobanana",
            ToolResult(ok=True, tool="nanobanana", artifact_path=artifact),
        )
        t = _thinker(anth, tools)
        result = t.think_substantive(_agent_input(), slot="night")

        assert result.category == "artifact"
        assert result.artifact_path == artifact
        # Tool was called with the candidate summary as the brief.
        assert tools.calls == [
            {
                "tool": "nanobanana",
                "brief": "Logo for saree wholesale, warm earthy palette",
            }
        ]
        # Draft prompt user message included the tool output.
        draft_user_msg = anth.calls[2]["messages"][0]["content"]
        assert "Tool Outputs" in draft_user_msg
        assert "nanobanana" in draft_user_msg


# ── Substantive loop — retry + fallback (never silent-day, per 2026-06-02) ──


class TestThinkSubstantiveRetryAndFallback:
    def test_critique_chosen_index_negative_falls_back_to_first(self):
        """Critique returning -1 used to mean silent-day at v1.0. At v1.1 we
        fall back to candidate 0 and proceed with draft+judge."""
        anth = FakeAnthropic()
        negative = json.dumps({"chosen_index": -1, "verdicts": []})
        anth.set_responses(
            [
                _brainstorm_canned(2),
                negative,
                "Sonal ji, namaste! आज का दिन कैसा रहा?",
                _judge_canned("pass"),
            ]
        )
        t = _thinker(anth, FakeToolRunner())
        result = t.think_substantive(_agent_input(), slot="morning")
        assert result.category != "silent-day"
        assert "Sonal ji" in (result.text or "")
        assert len(anth.calls) == 4

    def test_draft_silent_day_token_triggers_retry(self):
        """If a stale v1.0 prompt still emits <silent-day>, treat it as a
        draft failure and retry — never propagate it through."""
        anth = FakeAnthropic()
        anth.set_responses(
            [
                _brainstorm_canned(1),
                _critique_canned(0),
                "<silent-day>",  # first draft attempt
                "Sonal ji, namaste! कैसे हैं आज?",  # retry
                _judge_canned("pass"),
            ]
        )
        t = _thinker(anth, FakeToolRunner())
        result = t.think_substantive(_agent_input(), slot="morning")
        assert result.category != "silent-day"
        assert "Sonal ji" in (result.text or "")

    def test_judge_fails_then_passes_on_retry(self):
        """Judge rejects first draft, retry with feedback, second draft passes."""
        anth = FakeAnthropic()
        anth.set_responses(
            [
                _brainstorm_canned(1),
                _critique_canned(0),
                "अरे Sonal, kaisi ho?",  # tum + feminine → fails
                _judge_canned("fail"),
                "Sonal ji, namaste! कैसे हैं?",  # respectful → passes
                _judge_canned("pass"),
            ]
        )
        t = _thinker(anth, FakeToolRunner())
        result = t.think_substantive(_agent_input(), slot="night")
        assert result.category != "silent-day"
        assert result.text == "Sonal ji, namaste! कैसे हैं?"
        assert result.judge_verdict is not None
        assert result.judge_verdict["verdict"] == "pass"

    def test_all_draft_retries_fail_uses_safe_fallback_greeting(self):
        """After max_draft_retries failures, fall back to hand-authored
        aap-form greeting. NudgeCandidate still carries text."""
        anth = FakeAnthropic()
        anth.set_responses(
            [
                _brainstorm_canned(1),
                _critique_canned(0),
                "bad 1",
                _judge_canned("fail"),
                "bad 2",
                _judge_canned("fail"),
                "bad 3",
                _judge_canned("fail"),
            ]
        )
        t = _thinker(anth, FakeToolRunner())
        result = t.think_substantive(_agent_input(), slot="morning")
        assert result.category != "silent-day"
        assert "namaste" in (result.text or "")
        assert result.judge_verdict is not None
        assert result.judge_verdict["verdict"] == "fallback"

    def test_brainstorm_empty_uses_fallback_candidate(self):
        """Empty brainstorm → synthesize a safe candidate → proceed normally."""
        anth = FakeAnthropic()
        anth.set_responses(
            [
                json.dumps({"candidates": []}),  # empty
                _critique_canned(0),
                "Sonal ji, namaste! आज का दिन कैसा रहा?",
                _judge_canned("pass"),
            ]
        )
        t = _thinker(anth, FakeToolRunner())
        result = t.think_substantive(_agent_input(), slot="morning")
        assert result.category != "silent-day"
        assert "Sonal ji" in (result.text or "")

    def test_brainstorm_unparseable_falls_back_to_candidate(self):
        anth = FakeAnthropic()
        anth.set_responses(
            [
                "this is not json at all",  # brainstorm fails
                _critique_canned(0),
                "Sonal ji, namaste!",
                _judge_canned("pass"),
            ]
        )
        t = _thinker(anth, FakeToolRunner())
        result = t.think_substantive(_agent_input(), slot="morning")
        assert result.category != "silent-day"
        assert result.text is not None

    def test_critique_unparseable_falls_back_to_first(self):
        anth = FakeAnthropic()
        anth.set_responses(
            [
                _brainstorm_canned(2),
                "garbage",  # critique parse fails
                "Sonal ji, namaste!",
                _judge_canned("pass"),
            ]
        )
        t = _thinker(anth, FakeToolRunner())
        result = t.think_substantive(_agent_input(), slot="morning")
        assert result.category != "silent-day"
        assert result.text is not None

    def test_invalid_slot_raises(self):
        t = _thinker(FakeAnthropic(), FakeToolRunner())
        with pytest.raises(ValueError):
            t.think_substantive(_agent_input(), slot="afternoon")


# ── Joke loop — retry + fallback ────────────────────────────────


class TestThinkJoke:
    def test_happy_path(self):
        anth = FakeAnthropic()
        anth.set_responses(
            [
                "एक चोर ने मेरा calendar चुरा लिया।",
                _judge_canned("pass"),
            ]
        )
        t = _thinker(anth, FakeToolRunner())
        result = t.think_joke(_agent_input())
        assert result.slot == "afternoon"
        assert result.category == "joke"
        assert "calendar" in (result.text or "")

    def test_silent_day_token_triggers_retry(self):
        """v1.0 joke prompt could return <silent-day>; v1.1 treats it as a
        draft failure and retries."""
        anth = FakeAnthropic()
        anth.set_responses(
            [
                "<silent-day>",  # bad first attempt
                "एक चोर ने मेरा calendar चुरा लिया।",  # second attempt
                _judge_canned("pass"),
            ]
        )
        t = _thinker(anth, FakeToolRunner())
        result = t.think_joke(_agent_input())
        assert result.category == "joke"
        assert "calendar" in (result.text or "")

    def test_judge_rejects_first_joke_picks_another(self):
        anth = FakeAnthropic()
        anth.set_responses(
            [
                "Bad joke",
                _judge_canned("fail"),
                "एक चोर ने मेरा calendar चुरा लिया।",
                _judge_canned("pass"),
            ]
        )
        t = _thinker(anth, FakeToolRunner())
        result = t.think_joke(_agent_input())
        assert result.category == "joke"
        assert "calendar" in (result.text or "")

    def test_all_joke_retries_fail_uses_vault_fallback(self):
        """After max_joke_retries, fall back to the first vault joke
        unconditionally."""
        anth = FakeAnthropic()
        anth.set_responses(
            [
                "Bad 1",
                _judge_canned("fail"),
                "Bad 2",
                _judge_canned("fail"),
                "Bad 3",
                _judge_canned("fail"),
            ]
        )
        t = _thinker(anth, FakeToolRunner())
        result = t.think_joke(_agent_input())
        assert result.category == "joke"
        assert result.text is not None  # vault fallback always returns something
        assert result.judge_verdict is not None
        assert result.judge_verdict["verdict"] == "fallback"


# ── Piece D: thread_slug round-trip ─────────────────────────────────────


class TestThreadSlugRoundTrip:
    """Piece D wires the chosen open-thread through the thinker so the
    delivery hook can call ``mark_thread_nudged`` on the right slug."""

    def test_brainstorm_parses_thread_slug_when_present(self):
        anth = FakeAnthropic()
        anth.set_responses(
            [
                json.dumps(
                    {
                        "candidates": [
                            {
                                "category": "substantive",
                                "summary": "Check on the loan plan",
                                "trace": "open_threads: saree_biz dormant",
                                "tools_needed": [],
                                "why_now": "stale 14d",
                                "thread_slug": "saree_biz",
                            }
                        ]
                    }
                ),
                _critique_canned(0),
                "namaste Manimala ji",
                _judge_canned("pass"),
            ]
        )
        t = _thinker(anth, FakeToolRunner())
        result = t.think_substantive(_agent_input(), slot="morning")
        assert result.brainstorm_candidates[0].thread_slug == "saree_biz"
        # NudgeCandidate.thread_slug is populated from chosen candidate.
        assert result.thread_slug == "saree_biz"

    def test_missing_thread_slug_is_none_not_empty_string(self):
        """When the brainstorm output omits thread_slug (candidate
        grounded in a domain-file fact, not a thread), the parsed
        value must be ``None`` so the delivery hook knows to skip
        ``mark_thread_nudged``."""
        anth = FakeAnthropic()
        anth.set_responses(
            [
                _brainstorm_canned(1),  # no thread_slug field
                _critique_canned(0),
                "namaste",
                _judge_canned("pass"),
            ]
        )
        t = _thinker(anth, FakeToolRunner())
        result = t.think_substantive(_agent_input(), slot="morning")
        assert result.brainstorm_candidates[0].thread_slug is None
        assert result.thread_slug is None

    def test_empty_string_thread_slug_normalises_to_none(self):
        """LLMs occasionally emit ``"thread_slug": ""`` instead of
        ``null``. The parser must coerce to ``None`` so the delivery
        hook's truthy check skips correctly."""
        anth = FakeAnthropic()
        anth.set_responses(
            [
                json.dumps(
                    {
                        "candidates": [
                            {
                                "category": "substantive",
                                "summary": "x",
                                "trace": "y",
                                "tools_needed": [],
                                "why_now": "z",
                                "thread_slug": "",
                            }
                        ]
                    }
                ),
                _critique_canned(0),
                "namaste",
                _judge_canned("pass"),
            ]
        )
        t = _thinker(anth, FakeToolRunner())
        result = t.think_substantive(_agent_input(), slot="morning")
        assert result.thread_slug is None
