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
        # When web_search is enabled, pass the Anthropic server-side tool so
        # the model can ground specifics it doesn't know (local clinics, "box
        # cricket near Grant Road", etc.). Anthropic executes the search
        # server-side and merges results into the final response — no
        # client-side tool_use loop needed. max_uses enforced server-side.
        kwargs: dict = {
            "model": self.config.anthropic_model,
            "max_tokens": 1024,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
            "temperature": 0.4,
        }
        if self.config.web_search_enabled:
            kwargs["tools"] = [
                {
                    "type": self.config.web_search_tool_name,
                    "name": "web_search",
                    "max_uses": self.config.web_search_max_uses_per_call,
                }
            ]

        response = self.client.messages.create(**kwargs)

        if response.stop_reason == "max_tokens":
            import logging

            logging.getLogger("bhai.llm").warning(
                "Claude response truncated (hit max_tokens=%d)", 1024
            )

        # Concatenate ALL TextBlocks. With web_search, the model can emit
        # multiple text segments interleaved with server-tool-use and
        # web_search_tool_result blocks; taking only the first would drop
        # the actual answer in many cases.
        from anthropic.types import TextBlock

        text_parts = [b.text for b in response.content if isinstance(b, TextBlock)]
        return "\n".join(text_parts).strip()
