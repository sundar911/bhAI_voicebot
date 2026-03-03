Analyze the latest STT benchmarking results and generate a summary report.

Read the results from:
- benchmarking/results/ (CSV files)
- benchmarking/BENCHMARKING.md (for context on methodology)
- benchmarking/configs/models.yaml (model registry)

## Report should include

1. **Model ranking** by nWER (normalized Word Error Rate) — the primary metric
2. **Per-domain breakdown** — which model works best for each domain (hr_admin, helpdesk, production, grievance, nextgen)?
3. **Notable findings** — any surprising results or patterns
4. **Recommendation** — which model should be used in production and why
5. **Comparison with previous results** if available

Keep the report concise. Use tables. Focus on actionable insights.

If $ARGUMENTS specifies a domain, focus the analysis on that domain only.
