Review and update all markdown documentation in this project to reflect the current state of the codebase.

## Files to review

Root level:
- README.md — project overview, architecture, quick start, project structure tree
- CONTRIBUTING.md — contribution guidelines
- CLAUDE.md — this is YOUR reference file. Core principles and values must stay (they keep us grounded in who we're building for). But you should freely update technical/structural info: audio naming conventions, domain mappings, new architectural decisions, workflow notes — anything that helps you do your job better across sessions.

Benchmarking:
- benchmarking/README.md — scripts documentation, model list, metrics
- benchmarking/BENCHMARKING.md — detailed results and methodology
- benchmarking/EC2_SETUP.md — AWS setup guide

Data:
- data/README.md — data directory structure, JSONL format
- data/transcription_dataset/TRANSCRIPTION_GUIDELINES.md — transcription rules

Knowledge base:
- knowledge_base/README.md — editing guidelines for Tiny team

## What to check

1. **Project structure tree** in README.md — does it match the actual directory layout?
2. **Script documentation** — do the documented CLI commands still work? Are there new scripts not yet documented?
3. **Model list** in benchmarking docs — does it match `benchmarking/configs/models.yaml`?
4. **Dependencies and setup** — does pyproject.toml match what README says to install?
5. **Code examples** — are the documented import paths and function signatures still valid?
6. **Cross-references** — do links between docs point to files that exist?

## Scope: $ARGUMENTS

If an argument is provided (e.g., `/update-docs benchmarking`), only update docs in that area.
If no argument, do a full sweep of all files listed above.

## Rules

- Keep the existing tone and structure of each file — don't rewrite from scratch
- Only change information that is factually outdated
- Don't add new sections unless something important is completely undocumented
- Don't touch knowledge_base/hr_admin/ or knowledge_base/shared/ content files (those are maintained by the Tiny team)
- Show a summary of what you changed at the end
