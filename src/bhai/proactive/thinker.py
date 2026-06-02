"""ProactiveThinker — the agent loop for bhAI's proactive surface.

Implements the brainstorm → critique → tools → draft → judge sequence laid
out in tmp/v2_proactive_design.md §1. One ProactiveThinker instance is
constructed per dry-run (or per scheduler invocation in production) and
called once per slot per user.

Design notes:
- The agent uses Anthropic Sonnet for every pass at v1 (cost-optimisation
  to Haiku for the cheap critique/judge passes is a v2.5 knob — premature
  at 5 pilot users).
- Each pass uses the same Anthropic client, just different prompts +
  different temperatures (high for divergent brainstorm, lower for
  convergent critique/judge).
- All tool calls are dependency-injected through the constructor so tests
  can pass mocks without standing up real clients.
- The thinker NEVER writes to the user's permanent state. Its output is a
  NudgeCandidate object that the dry-run script logs (step 6c) or the
  delivery scheduler queues (step 8).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol

from ..config import Config
from .agent_input import AgentInput
from .prompts import (
    load_brainstorm_prompt,
    load_critique_prompt,
    load_draft_prompt,
    load_joke_prompt,
    load_joke_vault,
    load_judge_prompt,
)
from .tools._types import ToolResult

logger = logging.getLogger("bhai.proactive.thinker")


# ── Data classes ───────────────────────────────────────────────────────


@dataclass
class BrainstormCandidate:
    """One proposed proactive move from the brainstorm pass."""

    category: str  # "substantive" | "artifact" | "lesson" | "silent-day"
    summary: str
    trace: str
    tools_needed: List[str] = field(default_factory=list)
    why_now: str = ""


@dataclass
class NudgeCandidate:
    """The agent's final output for one slot — either a queued nudge or
    silent-day with reasoning."""

    slot: str  # "morning" | "afternoon" | "night"
    category: str  # "substantive" | "artifact" | "lesson" | "joke" | "silent-day"
    text: Optional[str] = None  # voice-note text, None for silent-day
    artifact_path: Optional[Path] = None
    chosen_candidate: Optional[BrainstormCandidate] = None
    silent_day_reason: Optional[str] = None

    # Full trace — preserved for the audit log and the portfolio review.
    brainstorm_candidates: List[BrainstormCandidate] = field(default_factory=list)
    critique_verdicts: List[Dict[str, Any]] = field(default_factory=list)
    judge_verdict: Optional[Dict[str, Any]] = None
    tool_results: List[Dict[str, Any]] = field(default_factory=list)


# ── Anthropic client protocol (for DI in tests) ──────────────────────


class AnthropicLike(Protocol):
    """Minimum interface the thinker depends on. The real anthropic.Anthropic
    client satisfies this; tests inject a fake."""

    def messages_create(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: List[Dict[str, str]],
        temperature: float,
    ) -> str: ...


def _make_anthropic_caller(api_key: str) -> AnthropicLike:
    """Build an AnthropicLike that wraps the real SDK. Imported lazily so
    test modules don't need the SDK installed (it's already a dep, but the
    lazy import means a thinker built with a mock never touches anthropic)."""
    import anthropic
    from anthropic.types import TextBlock

    client = anthropic.Anthropic(api_key=api_key)

    class _Caller:
        def messages_create(
            self,
            *,
            model: str,
            max_tokens: int,
            system: str,
            messages: List[Dict[str, str]],
            temperature: float,
        ) -> str:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,  # type: ignore[arg-type]
                temperature=temperature,
            )
            block = next(
                (b for b in response.content if isinstance(b, TextBlock)), None
            )
            return (block.text if block else "").strip()

    return _Caller()


# ── JSON parsing with fallback ──────────────────────────────────────


def _parse_json_response(raw: str) -> Dict[str, Any]:
    """Parse a model response that should be JSON.

    Handles three common LLM output shapes:
    1. Clean JSON.
    2. JSON wrapped in ```json … ``` code fences.
    3. JSON with leading/trailing prose (uncommon when prompted strictly).

    Raises ValueError if no JSON object can be located.
    """
    text = raw.strip()
    # Try clean first.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strip ```json or ``` fences if present.
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        return json.loads(fence_match.group(1))

    # Fallback: find the first { … last matching } heuristic.
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        try:
            return json.loads(text[first_brace : last_brace + 1])
        except json.JSONDecodeError as e:
            raise ValueError(f"could not parse JSON from model response: {e}")
    raise ValueError("no JSON object found in model response")


# ── Tool runner protocol ───────────────────────────────────────────


class ToolRunnerLike(Protocol):
    """Minimum interface for the tool layer the thinker depends on. Tests
    inject a fake; production passes a real `ToolRunner` (defined below)."""

    def run(
        self, tool_name: str, brief: str, agent_input: AgentInput
    ) -> ToolResult: ...


@dataclass
class ToolRunner:
    """Production tool runner — wires the four tool wrappers to the agent.

    Constructed once at thinker setup with all the shared config the tools
    need (API keys, model names, base dirs). The thinker calls .run() with
    just (tool_name, brief, agent_input).
    """

    config: Config
    artifacts_base_dir: Path
    audit_base_dir: Path
    kb_dir: Path
    tts: Any = None  # SarvamTTS-like, only needed for tts_draft

    def run(self, tool_name: str, brief: str, agent_input: AgentInput) -> ToolResult:
        from .tools.kb_read import read_kb_file
        from .tools.nanobanana import generate_image
        from .tools.tts_draft import synthesize
        from .tools.web_search import search

        artifacts_dir = self.artifacts_base_dir / agent_input.phone_hash / "artifacts"
        if tool_name == "nanobanana":
            return generate_image(
                brief=brief,
                dossier=agent_input.dossier,
                api_key=self.config.nanobanana_api_key,
                model=self.config.nanobanana_model,
                endpoint=self.config.nanobanana_endpoint,
                artifacts_dir=artifacts_dir,
                audit_base_dir=self.audit_base_dir,
            )
        if tool_name == "web_search":
            return search(
                query=brief,
                dossier=agent_input.dossier,
                api_key=self.config.google_search_api_key,
                cse_id=self.config.google_search_cse_id,
                audit_base_dir=self.audit_base_dir,
            )
        if tool_name == "kb_read":
            return read_kb_file(
                slug=brief,
                dossier=agent_input.dossier,
                kb_dir=self.kb_dir,
                audit_base_dir=self.audit_base_dir,
            )
        if tool_name == "tts_draft":
            if self.tts is None:
                return ToolResult(
                    ok=False,
                    tool="tts_draft",
                    error="tts_not_configured",
                )
            return synthesize(
                text=brief,
                dossier=agent_input.dossier,
                tts=self.tts,
                artifacts_dir=artifacts_dir,
                audit_base_dir=self.audit_base_dir,
            )
        return ToolResult(ok=False, tool=tool_name, error=f"unknown_tool: {tool_name}")


# ── The thinker itself ────────────────────────────────────────────


class ProactiveThinker:
    """Orchestrates the brainstorm → critique → tools → draft → judge loop
    for one user, one slot.

    Construct once per dry-run or scheduler tick; call `think_substantive()`
    for morning/night slots and `think_joke()` for the afternoon slot.
    """

    def __init__(
        self,
        config: Config,
        *,
        anthropic_caller: AnthropicLike,
        tool_runner: ToolRunnerLike,
        model: Optional[str] = None,
        max_tokens: int = 2048,
        max_draft_retries: int = 3,
        max_joke_retries: int = 3,
    ):
        self.config = config
        self.anthropic = anthropic_caller
        self.tools = tool_runner
        self.model = model or "claude-sonnet-4-6"
        self.max_tokens = max_tokens
        self.max_draft_retries = max_draft_retries
        self.max_joke_retries = max_joke_retries

    # ── Substantive slot loop ──────────────────────────────────────

    def think_substantive(self, agent_input: AgentInput, slot: str) -> NudgeCandidate:
        """Run the full agent loop for a morning or night substantive slot.

        Per Sundar's 2026-06-02 directive: never silent-day. On judge failure,
        retry the draft (with feedback) up to `max_draft_retries` times. If
        every retry fails, fall back to a safe gendered-neutral aap-form
        greeting tied to the chosen candidate's trace — better to send a
        plain check-in than nothing.
        """
        if slot not in ("morning", "night"):
            raise ValueError(f"think_substantive expects morning|night, got {slot!r}")

        # 1. Brainstorm. If empty, synthesize a fallback so we always proceed.
        candidates = self._brainstorm(agent_input, slot)
        if not candidates:
            candidates = [self._fallback_candidate(agent_input)]

        # 2. Critique. If parser failed (-1), fall back to first candidate.
        chosen_idx, verdicts, least_bad_note = self._critique(
            agent_input, candidates, slot
        )
        if chosen_idx < 0 or chosen_idx >= len(candidates):
            chosen_idx = 0
        chosen = candidates[chosen_idx]

        # 3. Tools (optional, depends on candidate).
        tool_results_full: List[ToolResult] = []
        tool_outputs_for_draft: Dict[str, Any] = {}
        for tool_name in chosen.tools_needed:
            brief = self._compose_tool_brief(tool_name, chosen, agent_input)
            result = self.tools.run(tool_name, brief, agent_input)
            tool_results_full.append(result)
            tool_outputs_for_draft[tool_name] = self._summarize_tool_result(result)

        # 4 + 5. Draft + judge with retry loop. Always lands on SOME text.
        draft_text = ""
        judge_verdict: Dict[str, Any] = {}
        prior_feedback = ""
        prior_drafts: List[str] = []
        for attempt in range(self.max_draft_retries):
            draft_text = self._draft(
                agent_input,
                chosen,
                tool_outputs_for_draft,
                slot,
                prior_feedback=prior_feedback,
                prior_drafts=prior_drafts,
            )
            if draft_text.strip() == "<silent-day>":
                # The v1 prompt could return this; the v1.1 prompt forbids
                # it but we defensively treat it as a draft failure and retry.
                prior_feedback = (
                    "previous attempt returned <silent-day>; you MUST produce "
                    "actual voice-note text, no silent-day output allowed"
                )
                prior_drafts.append(draft_text)
                continue
            judge_verdict = self._judge(agent_input, draft_text, chosen, slot)
            if judge_verdict.get("verdict") == "pass":
                break
            prior_feedback = judge_verdict.get("reasoning", "") or (
                "judge rejected the draft for an unstated reason"
            )
            prior_drafts.append(draft_text)
        else:
            # Every retry failed. Fall back to a safe minimal greeting so we
            # still send something — Sundar's "never silent-day" rule.
            draft_text = self._safe_fallback_greeting(agent_input, slot, chosen)
            judge_verdict = {
                "verdict": "fallback",
                "checks": {},
                "reasoning": (
                    f"used safe fallback after {self.max_draft_retries} judge "
                    f"failures; last feedback: {prior_feedback}"
                ),
            }

        # Resolve artifact path from the first artifact-producing tool result.
        artifact_path: Optional[Path] = None
        for r in tool_results_full:
            if r.ok and r.artifact_path is not None and r.tool == "nanobanana":
                artifact_path = r.artifact_path
                break

        return NudgeCandidate(
            slot=slot,
            category=chosen.category,
            text=draft_text,
            artifact_path=artifact_path,
            chosen_candidate=chosen,
            brainstorm_candidates=candidates,
            critique_verdicts=verdicts,
            judge_verdict=judge_verdict,
            tool_results=[self._tool_result_to_dict(r) for r in tool_results_full],
        )

    # ── Joke slot loop ─────────────────────────────────────────────

    def think_joke(self, agent_input: AgentInput) -> NudgeCandidate:
        """Compose a single joke for the afternoon slot.

        Per Sundar's 2026-06-02 directive: never silent-day on jokes. If the
        judge rejects a joke, re-invoke the joke pass with the rejected
        text excluded; retry up to `max_joke_retries` times. If every retry
        fails, fall back to the first vault joke unconditionally.
        """
        stub_candidate = BrainstormCandidate(
            category="joke",
            summary="dad-joke from vault",
            trace="joke vault (jokes_v1_*.md)",
            tools_needed=[],
            why_now="afternoon mood lift",
        )

        prior_jokes: List[str] = []
        judge_verdict: Dict[str, Any] = {}
        joke_text = ""
        for attempt in range(self.max_joke_retries):
            joke_text = self._joke(agent_input, exclude_jokes=prior_jokes)
            stripped = joke_text.strip()
            if stripped == "<silent-day>" or stripped in prior_jokes:
                # v1.1 forbids silent-day; treat as "try again". Same for
                # exact-text repeats.
                prior_jokes.append(stripped)
                continue
            judge_verdict = self._judge(
                agent_input, joke_text, stub_candidate, "afternoon"
            )
            if judge_verdict.get("verdict") == "pass":
                return NudgeCandidate(
                    slot="afternoon",
                    category="joke",
                    text=joke_text,
                    judge_verdict=judge_verdict,
                )
            prior_jokes.append(stripped)

        # All retries failed — fall back to the first vault joke
        # unconditionally so we always send something.
        fallback_text = self._fallback_joke()
        return NudgeCandidate(
            slot="afternoon",
            category="joke",
            text=fallback_text,
            judge_verdict={
                "verdict": "fallback",
                "checks": {},
                "reasoning": (
                    f"used fallback vault joke after {self.max_joke_retries} "
                    f"judge failures; last text: {joke_text!r}"
                ),
            },
        )

    # ── Pass implementations ──────────────────────────────────────

    def _brainstorm(
        self, agent_input: AgentInput, slot: str
    ) -> List[BrainstormCandidate]:
        system = load_brainstorm_prompt()
        user = self._build_user_message(
            agent_input=agent_input,
            slot=slot,
            extra_sections={},
        )
        raw = self.anthropic.messages_create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            temperature=0.7,  # divergent
        )
        try:
            parsed = _parse_json_response(raw)
            return [
                BrainstormCandidate(
                    category=c.get("category", "substantive"),
                    summary=c.get("summary", ""),
                    trace=c.get("trace", ""),
                    tools_needed=c.get("tools_needed", []) or [],
                    why_now=c.get("why_now", ""),
                )
                for c in parsed.get("candidates", [])
            ]
        except Exception as e:
            logger.warning(
                "brainstorm parse failed for %s: %s", agent_input.phone_hash, e
            )
            return []

    def _critique(
        self,
        agent_input: AgentInput,
        candidates: List[BrainstormCandidate],
        slot: str,
    ) -> tuple[int, List[Dict[str, Any]], Optional[str]]:
        system = load_critique_prompt()
        candidates_json = json.dumps(
            [
                {
                    "category": c.category,
                    "summary": c.summary,
                    "trace": c.trace,
                    "tools_needed": c.tools_needed,
                    "why_now": c.why_now,
                }
                for c in candidates
            ],
            ensure_ascii=False,
            indent=2,
        )
        user = self._build_user_message(
            agent_input=agent_input,
            slot=slot,
            extra_sections={"Brainstorm Output": candidates_json},
        )
        raw = self.anthropic.messages_create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            temperature=0.2,  # convergent
        )
        try:
            parsed = _parse_json_response(raw)
            return (
                int(parsed.get("chosen_index", -1)),
                parsed.get("verdicts", []),
                parsed.get("silent_day_reason"),
            )
        except Exception as e:
            logger.warning(
                "critique parse failed for %s: %s", agent_input.phone_hash, e
            )
            return -1, [], f"critique parse error: {e}"

    def _draft(
        self,
        agent_input: AgentInput,
        chosen: BrainstormCandidate,
        tool_outputs: Dict[str, Any],
        slot: str,
        *,
        prior_feedback: str = "",
        prior_drafts: Optional[List[str]] = None,
    ) -> str:
        system = load_draft_prompt()
        chosen_json = json.dumps(
            {
                "category": chosen.category,
                "summary": chosen.summary,
                "trace": chosen.trace,
                "tools_needed": chosen.tools_needed,
                "why_now": chosen.why_now,
            },
            ensure_ascii=False,
            indent=2,
        )
        extra = {"Chosen Candidate": chosen_json}
        if tool_outputs:
            extra["Tool Outputs"] = json.dumps(
                tool_outputs, ensure_ascii=False, indent=2
            )
        if prior_drafts and prior_feedback:
            # Tell the model what went wrong last time + what to avoid.
            extra["Previous Attempts (failed judge)"] = (
                "\n---\n".join(prior_drafts)
                + f"\n\n=== Judge feedback ===\n{prior_feedback}\n\n"
                "Produce a different draft that addresses the feedback above. "
                "Do NOT silent-day."
            )
        user = self._build_user_message(
            agent_input=agent_input, slot=slot, extra_sections=extra
        )
        raw = self.anthropic.messages_create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            temperature=0.6,  # moderately divergent for voice
        )
        return raw.strip()

    def _judge(
        self,
        agent_input: AgentInput,
        draft_text: str,
        chosen: BrainstormCandidate,
        slot: str,
    ) -> Dict[str, Any]:
        system = load_judge_prompt()
        extra = {
            "Draft Text": draft_text,
            "Chosen Candidate": json.dumps(
                {
                    "category": chosen.category,
                    "summary": chosen.summary,
                    "trace": chosen.trace,
                    "tools_needed": chosen.tools_needed,
                    "why_now": chosen.why_now,
                },
                ensure_ascii=False,
                indent=2,
            ),
        }
        user = self._build_user_message(
            agent_input=agent_input, slot=slot, extra_sections=extra
        )
        raw = self.anthropic.messages_create(
            model=self.model,
            max_tokens=512,
            system=system,
            messages=[{"role": "user", "content": user}],
            temperature=0.1,
        )
        try:
            return _parse_json_response(raw)
        except Exception as e:
            logger.warning("judge parse failed for %s: %s", agent_input.phone_hash, e)
            # If the judge fails to produce parseable JSON, fail-closed
            # (better to skip a slot than push an unvalidated nudge).
            return {
                "verdict": "fail",
                "checks": {},
                "reasoning": f"judge_parse_error: {e}",
            }

    def _joke(
        self,
        agent_input: AgentInput,
        *,
        exclude_jokes: Optional[List[str]] = None,
    ) -> str:
        system = load_joke_prompt()
        extra: Dict[str, str] = {
            "Joke Vault (Hindi v1)": load_joke_vault(language="hi"),
            "Joke Vault (English v1)": load_joke_vault(language="en"),
        }
        if exclude_jokes:
            extra["Already Tried This Slot (do not repeat)"] = (
                "\n---\n".join(exclude_jokes)
                + "\n\nPick a DIFFERENT joke — vault preferred, fresh-compose only "
                "if vault is exhausted. Do NOT silent-day."
            )
        user = self._build_user_message(
            agent_input=agent_input, slot="afternoon", extra_sections=extra
        )
        raw = self.anthropic.messages_create(
            model=self.model,
            max_tokens=512,
            system=system,
            messages=[{"role": "user", "content": user}],
            temperature=0.5,
        )
        return raw.strip()

    # ── Helpers ───────────────────────────────────────────────────

    def _build_user_message(
        self,
        *,
        agent_input: AgentInput,
        slot: str,
        extra_sections: Dict[str, str],
    ) -> str:
        """Assemble the per-pass user message — dossier + recent + slot +
        any pass-specific extra sections."""
        parts = [
            "=== Dossier ===",
            agent_input.as_system_prompt_context(),
            "",
            agent_input.as_user_message_context(),
            "",
            f"=== Slot ===\n{slot}",
        ]
        for header, body in extra_sections.items():
            parts.extend(["", f"=== {header} ===", body])
        parts.extend(
            ["", "=== Task ===", "Produce your output per the system prompt's spec."]
        )
        return "\n".join(parts)

    def _compose_tool_brief(
        self,
        tool_name: str,
        chosen: BrainstormCandidate,
        agent_input: AgentInput,
    ) -> str:
        """Construct the brief sent to the tool wrapper.

        For v1 we use a deterministic template per tool. The agent prompt
        could in principle compose the brief itself — that's a v1.5 knob
        we'll add when we see the dry-run portfolio and judge whether the
        template approach is too restrictive.
        """
        if tool_name == "nanobanana":
            # The candidate's summary already describes the artifact intent —
            # treat it as the seed brief. The scrub layer will reject it if
            # it leaked PII; the draft pass handles the retry.
            return chosen.summary
        if tool_name == "web_search":
            return chosen.summary
        if tool_name == "kb_read":
            # KB read expects a file slug — try to extract one from the
            # candidate's summary or trace, fall back to the trace text.
            return chosen.trace
        return chosen.summary

    def _summarize_tool_result(self, result: ToolResult) -> Dict[str, Any]:
        """Compact tool-result shape for the draft prompt's user message."""
        if not result.ok:
            return {"ok": False, "error": result.error}
        if result.tool == "nanobanana":
            return {
                "ok": True,
                "tool": "nanobanana",
                "artifact_path": str(result.artifact_path),
            }
        if result.tool == "web_search":
            return {
                "ok": True,
                "tool": "web_search",
                "results": result.payload,
            }
        if result.tool == "kb_read":
            return {
                "ok": True,
                "tool": "kb_read",
                "content": (result.payload or "")[:2000],  # truncate for prompt
            }
        return {"ok": True, "tool": result.tool}

    def _tool_result_to_dict(self, result: ToolResult) -> Dict[str, Any]:
        return {
            "tool": result.tool,
            "ok": result.ok,
            "error": result.error,
            "artifact_path": (
                str(result.artifact_path) if result.artifact_path else None
            ),
        }

    # ── Fallbacks (Sundar's "never silent-day" rule) ──────────────────

    def _fallback_candidate(self, agent_input: AgentInput) -> BrainstormCandidate:
        """Synthesize a minimal safe candidate when brainstorm returns empty.

        Used only when the brainstorm pass parser-errors or returns zero
        candidates. The candidate just instructs the draft pass to send a
        warm aap-form check-in tied to the user's name (or "didi" if no
        name is known).
        """
        name = ""
        for f in agent_input.dossier.core_facts:
            if f.lower().startswith("naam:") or f.lower().startswith("name:"):
                name = f.split(":", 1)[1].strip()
                break
        addressed = name or "दीदी"
        return BrainstormCandidate(
            category="substantive",
            summary=f"Warm aap-form check-in with {addressed}",
            trace="fallback — brainstorm returned no candidates",
            tools_needed=[],
            why_now=(
                "always-send-something fallback; brainstorm couldn't surface a "
                "specific thread but a respectful check-in is still welcome"
            ),
        )

    def _safe_fallback_greeting(
        self,
        agent_input: AgentInput,
        slot: str,
        chosen: BrainstormCandidate,
    ) -> str:
        """Minimal aap-form greeting used after all draft retries fail.

        Hand-authored template guaranteed to pass the respectful-speech
        check. Sundar's rule: better a plain greeting than nothing.
        """
        name = ""
        for f in agent_input.dossier.core_facts:
            if f.lower().startswith("naam:") or f.lower().startswith("name:"):
                name = f.split(":", 1)[1].strip()
                break
        addressed = f"{name} ji" if name else "दीदी"
        if slot == "morning":
            return (
                f"{addressed}, namaste! आज का दिन कैसा शुरू हो रहा है? "
                "बताइएगा जब time मिले — सुनना है मुझे।"
            )
        # night
        return (
            f"{addressed}, namaste! आज का दिन कैसा रहा? "
            "बताइएगा जब आराम से बैठें — सुनने का मन है।"
        )

    def _fallback_joke(self) -> str:
        """First joke from the Hindi vault — guaranteed-safe fallback when
        every joke-pass retry fails the judge."""
        vault = load_joke_vault(language="hi")
        lines = vault.splitlines()
        in_joke = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("## Joke"):
                in_joke = True
                continue
            if in_joke and stripped.startswith("*tags:"):
                continue
            if (
                in_joke
                and stripped
                and not stripped.startswith("#")
                and not stripped.startswith("---")
            ):
                return stripped
        return "एक चोर ने मेरा calendar चुरा लिया। बेचारे को साल भर की जेल हो जाएगी अब।"
