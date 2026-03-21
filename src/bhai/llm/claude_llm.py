"""
Claude (Anthropic) LLM backend implementation.
Uses the Anthropic Messages API.
"""

from pathlib import Path
from typing import Optional

import anthropic

from ..config import Config
from .base import BaseLLM


class ClaudeLLM(BaseLLM):
    """Claude LLM backend via the Anthropic Messages API."""

    def __init__(
        self,
        config: Config,
        knowledge_base_dir: Optional[Path] = None,
    ):
        super().__init__(config, knowledge_base_dir)
        if not config.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY required when llm_backend='claude'. "
                "Set it in environment or .env."
            )
        self.client = anthropic.Anthropic(api_key=config.anthropic_api_key)

    @property
    def model_name(self) -> str:
        return self.config.anthropic_model

    def _call_api(self, system_prompt: str, user_message: str) -> str:
        response = self.client.messages.create(
            model=self.config.anthropic_model,
            max_tokens=512,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
            temperature=0.4,
        )
        from anthropic.types import TextBlock

        block = next((b for b in response.content if isinstance(b, TextBlock)), None)
        return (block.text if block else "").strip()
