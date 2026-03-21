"""
LLM backend factory.

Usage:
    from src.bhai.llm import create_llm
    llm = create_llm(config)
    result = llm.generate(transcript, domain="hr_admin")
"""

from pathlib import Path
from typing import Optional

from .base import BaseLLM


def create_llm(config, knowledge_base_dir: Optional[Path] = None) -> BaseLLM:
    """Create an LLM instance based on config.llm_backend."""
    backend = getattr(config, "llm_backend", "sarvam")

    if backend == "openai":
        from .openai_llm import OpenAILLM

        return OpenAILLM(config, knowledge_base_dir)
    elif backend == "claude":
        from .claude_llm import ClaudeLLM

        return ClaudeLLM(config, knowledge_base_dir)
    else:  # "sarvam" (default)
        from .sarvam_llm import SarvamLLM

        return SarvamLLM(config, knowledge_base_dir)
