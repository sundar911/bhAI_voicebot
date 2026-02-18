# Contributing to bhAI Voice Bot

Welcome! This guide helps Tiny Miracles team members and developers contribute effectively.

## For Tiny Miracles Team

### Editing Knowledge Base Content

You can directly edit files in `knowledge_base/` without needing to understand the code.

#### What You Can Edit

| Folder | Purpose | Who Should Edit |
|--------|---------|-----------------|
| `knowledge_base/hr_admin/` | Salary, leave, benefits info | HR team |
| `knowledge_base/helpdesk/` | Govt schemes, documents | Helpdesk team |
| `knowledge_base/production/` | Factory floor info | Production team |
| `knowledge_base/shared/` | Company overview, escalation rules | All teams (carefully) |

Just a loose structure, feel free to change it up completely as you see fit. It just needs to work for further LLM processing.

#### How to Edit

Use **Claude Code** (connected to this GitHub repo). Just tell it what to change:

- *"Update the leave policy in knowledge_base/hr_admin/policies.md to include 10 days maternity leave"*
- *"Add a new section about PF withdrawal to knowledge_base/hr_admin/benefits.md"*

Claude Code will edit the file, create a branch, and push the changes. Sundar reviews and approves.

#### Writing Guidelines

- Use **simple Hindi** that workers understand
- Keep answers **short** (20-40 seconds when spoken)
- Use **bullet points** for steps
- Include **common questions** workers ask

Example:
```markdown
## Chutti Kaise Le?

1. Team lead ko message karo
2. Reason batao - sick/planned/emergency
3. Jaldi batao, late mat karo

### "Kal nahi aa paungi"
→ Jaldi WhatsApp karo. Reason batao. Calendar me mark hoga.
```


## For Developers

### Setup

```bash
# Install dependencies
uv sync

# Copy environment file
cp .env.example .env
# Add your API keys

# Run tests
uv run pytest
```

### Code Structure

```
src/bhai/
├── stt/base.py          # Abstract STT interface
├── tts/base.py          # Abstract TTS interface
├── llm/base.py          # Abstract LLM interface
├── pipelines/base_pipeline.py  # Pipeline orchestration
└── config.py            # Configuration management
```

### Adding a New STT Backend

1. Create `src/bhai/stt/your_stt.py`
2. Inherit from `BaseSTT`
3. Implement `transcribe()` and `model_name` property
4. Add to benchmarking configs

Example:
```python
from .base import BaseSTT

class YourSTT(BaseSTT):
    def transcribe(self, audio_path: Path) -> Dict[str, Any]:
        # Your implementation
        return {"text": "...", "raw": {...}}

    @property
    def model_name(self) -> str:
        return "your-model-name"
```

### Git Workflow

#### Branches

- `main` - Production-ready code
- `develop` - Integration branch
- `stt/batch-XXX` - STT first-pass branches
- `review/domain-batch-XXX` - Human review branches
- `feature/XXX` - New features

#### Commit Messages

Use clear, descriptive messages:
- `Add: new leave policy content`
- `Fix: STT timeout issue`
- `Update: hr_admin payroll info`
- `Review: corrected batch 001 transcriptions`

### Testing

```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest src/tests/test_stt.py

# Run with coverage
uv run pytest --cov=src/bhai
```

### Code Style

- Use Python 3.10+ features
- Type hints for all functions
- Docstrings for public methods
- Format with `black` and `isort`

## Questions?

- Open a GitHub issue for bugs
- Ask in the team Slack for questions
- Check existing docs first
