"""Prompt-loading helpers for the proactive thinking agent.

Each prompt lives in its own markdown file in this directory. The agent
loop reads them once at startup (or per-test) via the load_* functions
below. Versioning is by filename suffix (`brainstorm_v1.md`, `joke_v1.md`);
to ship a v2 prompt, add a new file and update the default version below.
"""

from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent


def _load(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


def load_brainstorm_prompt(version: str = "v1") -> str:
    return _load(f"brainstorm_{version}.md")


def load_critique_prompt(version: str = "v1") -> str:
    return _load(f"critique_{version}.md")


def load_draft_prompt(version: str = "v1") -> str:
    return _load(f"draft_{version}.md")


def load_judge_prompt(version: str = "v1") -> str:
    return _load(f"judge_{version}.md")


def load_joke_prompt(version: str = "v1") -> str:
    return _load(f"joke_{version}.md")


def load_checkin_prompt(version: str = "v1") -> str:
    return _load(f"checkin_{version}.md")


def load_joke_vault(language: str = "hi", version: str = "v1") -> str:
    """Load the joke vault for a given language. Defaults to Hindi v1."""
    return _load(f"joke_vault/jokes_{version}_{language}.md")
