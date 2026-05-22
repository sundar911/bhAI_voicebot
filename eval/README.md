# bhAI golden-conversation eval

Five canned multi-turn scenarios, each scored by Claude as judge against a per-scenario rubric. Every prompt edit should pass all five before landing on `main`.

## Layout

```
eval/
├── README.md                          (this file)
├── run_eval.py                        runner
└── golden_conversations/
    ├── sapna_karate.json              outreach lie scenario
    ├── manimala_loan.json             sycophancy / math-led financial scenario
    ├── user_n_distress.json           first-message-distress / no-अरे scenario
    ├── kb_miss_driving_license.json   confabulation-via-helpfulness scenario
    └── language_mix.json              reasoning-leak provocation
```

Each scenario file is a JSON object:
```json
{
  "name": "...",
  "description": "what this tests",
  "turns": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "expected": "what bhAI should do next"}
  ],
  "must_contain": ["regex or substring patterns the final response must contain"],
  "must_not_contain": ["patterns that disqualify the response"],
  "judge_criterion": "free-text rubric Claude evaluates against"
}
```

## Running

```
uv run python eval/run_eval.py
```

Requires `ANTHROPIC_API_KEY` in env (uses Claude as both the system under test AND the judge). Prints per-scenario pass/fail and an aggregate summary.

## When a scenario fails

Don't auto-fix the rubric — investigate whether the failure is a regression in the prompt, a flaky judge, or a scenario that needs sharpening. The eval is the gating signal; it should be trustworthy.
