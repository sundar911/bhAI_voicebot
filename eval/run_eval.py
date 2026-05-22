"""
Golden-conversation eval runner.

Runs every JSON scenario in ``golden_conversations/`` against the active
prompt + Sonnet backend, then uses Claude as the judge to score whether the
response satisfies the rubric.

Usage:
    uv run python eval/run_eval.py
    uv run python eval/run_eval.py --scenario sapna_karate
    uv run python eval/run_eval.py --backend claude

Exit code is 0 if all scenarios pass, 1 if any fail. Suitable for CI.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure src/ is importable
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from bhai.llm import create_llm  # noqa: E402

SCENARIOS_DIR = Path(__file__).parent / "golden_conversations"

JUDGE_PROMPT_TEMPLATE = """You are evaluating a response from bhAI, a Hindi voice bot for women artisans at Tiny Miracles in Mumbai.

Below is the scenario rubric and the actual response bhAI produced. Decide whether the response **passes** the rubric.

=== Scenario ===
Name: {name}
Description: {description}

=== Last user message ===
{user_message}

=== bhAI's response ===
{response}

=== Rubric ===
{judge_criterion}

=== Hard constraints ===
The response MUST NOT contain any of these patterns (regex, case-sensitive Devanagari/English): {must_not_contain}
The response MUST contain at least one of these patterns (regex): {must_contain_any}

=== Your task ===
Reply with exactly two lines:
LINE 1 — `VERDICT: PASS` or `VERDICT: FAIL`
LINE 2 — One sentence explaining why. If FAIL, name the specific rubric criterion or pattern that was violated.

Be strict. A response that's warm and friendly but violates a hard constraint is a FAIL."""


@dataclass
class ScenarioResult:
    name: str
    passed: bool
    response: str
    reason: str
    must_not_violations: List[str]
    must_contain_satisfied: bool


def _check_patterns(text: str, patterns: List[str]) -> List[str]:
    """Return the subset of `patterns` that appear in `text`."""
    hits = []
    for pat in patterns or []:
        try:
            if re.search(pat, text):
                hits.append(pat)
        except re.error:
            # fall back to substring match for invalid regex
            if pat in text:
                hits.append(pat)
    return hits


def _any_match(text: str, patterns: List[str]) -> bool:
    if not patterns:
        return True
    for pat in patterns:
        try:
            if re.search(pat, text):
                return True
        except re.error:
            if pat in text:
                return True
    return False


def _load_scenarios(filter_name: Optional[str] = None) -> List[Dict[str, Any]]:
    scenarios = []
    for path in sorted(SCENARIOS_DIR.glob("*.json")):
        with path.open() as fp:
            scn = json.load(fp)
        scn["_path"] = str(path)
        if filter_name and scn.get("name") != filter_name:
            continue
        scenarios.append(scn)
    return scenarios


def _run_scenario(scn: Dict[str, Any], llm) -> ScenarioResult:
    # For a single-turn scenario, we just take the last user turn and ask
    # bhAI to respond. Multi-turn scenarios feed prior turns via the
    # conversation_history parameter of generate().
    turns = scn["turns"]
    history: List[Dict[str, str]] = []
    for turn in turns[:-1]:
        history.append({"role": turn["role"], "content": turn["content"]})
    last_user_turn = next(t for t in reversed(turns) if t["role"] == "user")

    result = llm.generate(
        transcript=last_user_turn["content"],
        domain="helpdesk",
        conversation_history=history if history else None,
        is_new_session=not history,
    )
    response = result.get("text", "")

    # Hard-constraint pre-checks
    must_not_violations = _check_patterns(response, scn.get("must_not_contain", []))
    must_contain_ok = _any_match(response, scn.get("must_contain_any", []))

    hard_passed = not must_not_violations and must_contain_ok

    # LLM-judge check (independent of hard constraints — we want to know
    # both whether the regex caught a violation AND whether the judge thinks
    # the response is good in spirit)
    judge_prompt = JUDGE_PROMPT_TEMPLATE.format(
        name=scn["name"],
        description=scn["description"],
        user_message=last_user_turn["content"],
        response=response,
        judge_criterion=scn["judge_criterion"],
        must_not_contain=", ".join(repr(p) for p in scn.get("must_not_contain", [])) or "(none)",
        must_contain_any=", ".join(repr(p) for p in scn.get("must_contain_any", [])) or "(none)",
    )

    judge_raw = llm._call_api_with_retry(judge_prompt, "")
    verdict_match = re.search(r"VERDICT:\s*(PASS|FAIL)", judge_raw, re.IGNORECASE)
    judge_passed = bool(verdict_match) and verdict_match.group(1).upper() == "PASS"
    reason = judge_raw.split("\n", 1)[-1].strip() if "\n" in judge_raw else judge_raw.strip()

    overall_passed = hard_passed and judge_passed

    if must_not_violations:
        reason = f"hard-constraint violations: {must_not_violations}. Judge: {reason}"
    elif not must_contain_ok:
        reason = f"none of must_contain_any matched. Judge: {reason}"

    return ScenarioResult(
        name=scn["name"],
        passed=overall_passed,
        response=response,
        reason=reason,
        must_not_violations=must_not_violations,
        must_contain_satisfied=must_contain_ok,
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", help="run only this scenario (by name)")
    parser.add_argument(
        "--backend",
        default=os.environ.get("LLM_BACKEND", "claude"),
        help="LLM backend (claude/sarvam/openai); default from $LLM_BACKEND or 'claude'",
    )
    parser.add_argument(
        "--prompt-version",
        default=os.environ.get("PROMPT_VERSION", "prompt_v1_pilot"),
        help="prompt version to test; default from $PROMPT_VERSION or 'prompt_v1_pilot'",
    )
    args = parser.parse_args(argv)

    os.environ.setdefault("LLM_BACKEND", args.backend)
    os.environ.setdefault("PROMPT_VERSION", args.prompt_version)

    scenarios = _load_scenarios(args.scenario)
    if not scenarios:
        print(f"No scenarios found (filter: {args.scenario!r})", file=sys.stderr)
        return 1

    llm = create_llm()
    print(f"Backend: {args.backend} | Prompt: {args.prompt_version} | Scenarios: {len(scenarios)}")
    print("=" * 72)

    results: List[ScenarioResult] = []
    for scn in scenarios:
        print(f"\n[{scn['name']}] {scn['description'][:80]}...")
        result = _run_scenario(scn, llm)
        results.append(result)
        marker = "✓ PASS" if result.passed else "✗ FAIL"
        print(f"  {marker} — {result.reason[:160]}")
        if not result.passed:
            print(f"  Response: {result.response[:200]}...")

    print("\n" + "=" * 72)
    passed = sum(1 for r in results if r.passed)
    print(f"Summary: {passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
