---
description: Identify untested code in the recent diff and propose tests for the gaps
---

Inspect recent code changes and write tests for behavior that isn't yet covered. Use this after adding a new capability — endpoint, prompt rule, integration, behavior contract — and before opening a PR.

## Scope

If `$ARGUMENTS` is empty, default to the diff between `HEAD~1` and `HEAD`.
If `$ARGUMENTS` is a commit ref (e.g. `HEAD~5..HEAD`, `main..HEAD`, `<commit-sha>`), use that range.
If `$ARGUMENTS` names a file path, scope to that file only.

## Procedure

### Phase 1 — Inventory what changed

1. Run `git diff --stat $RANGE` to list modified files. Filter to `.py` files in `src/bhai/` and `inference/` — those are the production paths that need tests. Skip `src/tests/`, `scripts/`, `benchmarking/`.
2. For each changed file, run `git diff $RANGE -- $FILE` and identify:
   - New top-level functions / classes / methods
   - New FastAPI route decorators (`@app.get`, `@app.post`)
   - New env-var reads (suggests a new config field)
   - New external API calls (LLM, Telegram, Resend, etc.)
   - New SQLite schema (new `CREATE TABLE` or `ALTER TABLE`)
3. For each module touched, identify the test file that *should* cover it (`src/bhai/llm/base.py` → `src/tests/test_llm_base.py`; `inference/webhooks/telegram_webhook.py` → `src/tests/test_telegram_webhook.py`). If no test file exists, that's the first gap.

### Phase 2 — Decide what to test

For each new function/class/route, classify the test type needed:

- **Unit test** — pure-function logic with no I/O. Example: a new regex helper, a new pure data transformation. Use mocks for any external dependency.
- **Behavioral contract** — assert on output shape rules, not just return values. Example: "the response must not contain certain markers", "the prompt template must contain certain phrases". Goes in `src/tests/test_contracts.py`.
- **Plumbing test** — exercises wiring between layers with mocked clients. Example: "voice update in → send_voice called with right shape". Goes in `src/tests/test_contracts.py` or the module's own test file.
- **Schema/migration test** — for any new SQLite table/column, assert it's created and round-trips encrypted data correctly. Goes in `src/tests/test_memory.py`.

Skip tests for:
- Pure prompt-text changes in `*.md` (unless the change is structural — adding/removing a rule section, which warrants a content-contract test in `test_contracts.py`)
- Documentation-only changes (`*.md` outside `prompts/`)
- Test files themselves (don't write tests for tests)

### Phase 3 — Draft the tests

For each gap, write a test that:

1. **Names the failure mode in the test name.** `test_kb_router_falls_back_when_haiku_unavailable` beats `test_kb_router_2`. Future devs reading a red CI log should immediately understand what regressed.
2. **Mocks external dependencies** — Anthropic, Telegram, Sarvam, SMTP — never make real API calls in tests. Use the `BHAI_ENCRYPTION_KEY` fixture from `src/tests/conftest.py` for any code that touches encryption.
3. **Asserts on observable contracts**, not implementation details. "The webhook returns 200 and `send_voice` was called once" beats "the internal `_process_audio` ran 3 times".
4. **Includes one regression test for any failure mode mentioned in the commit message.** If the commit says "fixes X", write a test that fails without the fix.

### Phase 4 — Run + report

1. Write the tests to the appropriate `src/tests/test_*.py` files (extend existing files; create new ones only if the module has no existing test file).
2. Run `uv run pytest src/tests/ -q` and confirm everything still passes.
3. Run `uv run black --check src/tests/` and `uv run isort --check-only src/tests/` — autofix if needed.
4. Print a summary to the user:
   - Files changed in the diff
   - Test gaps identified
   - New tests added (filename + test name)
   - Final pass count

## Things to watch for (from past pilot failures)

- **Half-committed modules** — if the diff references an import (`from .foo import Bar`) and `foo.py` is not in the diff but also doesn't exist on disk, that's the May 11 failure mode. The `import-smoke` CI job catches this; you can also catch it by adding/extending a test that imports the changed module.
- **LLM behavior regressions** — when a prompt rule changes, the only test that catches a regression is a content-contract test that asserts the rule text exists in the prompt file. Add to `test_contracts.py::test_prompt_template_contains_*` family.
- **CoT leakage shapes** — any new prompt section that talks about rules/policies is a fresh CoT-leak risk. If you add such a section, also add a regression test feeding a plausible leak shape into `_strip_reasoning_leak`.
- **Untested admin endpoints** — every `/admin/*` route needs at minimum: auth-required test (403 without key), happy-path test (200 with key), and idempotency (calling twice is safe or errors cleanly).

## Output format

Keep it short. The user wants to know what you found and what you wrote, not a step-by-step narration.

```
Diff: HEAD~1..HEAD (4 files)
  src/bhai/integrations/email_client.py (NEW, 87 lines)
  inference/webhooks/telegram_webhook.py (+42 lines)
  src/bhai/memory/store.py (+18 lines)
  src/bhai/config.py (+6 lines)

Gaps identified:
  - email_client.ResendClient — no test file
  - telegram_webhook /admin/digest-now — no test
  - store.record_escalation — no test (also new schema)

Tests written:
  src/tests/test_email_client.py — 4 tests (NEW file)
  src/tests/test_telegram_webhook.py::test_digest_now_requires_key — added
  src/tests/test_memory.py::test_record_escalation_round_trips — added
  src/tests/test_contracts.py::test_outreach_rule_still_in_prompt — added (regression)

uv run pytest src/tests/ -q
  199 passed in 0.71s
```

If something can't be tested (e.g., requires a real Resend API key), say so explicitly and explain why. Don't write a fake test that pretends to cover it.
