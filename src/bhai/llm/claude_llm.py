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

    # Seed the assistant turn with the start of the JSON object. This forces
    # the model to begin inside the structured contract (cot first, in order)
    # and makes it physically impossible to emit preamble or chain-of-thought
    # before the JSON — the leak is prevented at generation time, not scrubbed
    # afterwards. We re-attach the prefill to the returned text before parsing.
    _PREFILL = '{"cot":'

    # Higher than the old 1024: cot + out share the budget, so leave headroom
    # for a complete out (long helpdesk answers) after the reasoning.
    _MAX_TOKENS = 2048

    def _call_api(self, system_prompt: str, user_message: str) -> str:
        """Plain call — NO JSON prefill.

        Used by callers that expect free-form text (summarizer, nudges). These
        must NOT be forced into the cot/out JSON contract, or their output gets
        corrupted (and, for nudges, leaks JSON straight to the user).
        """
        return self._messages_create(system_prompt, user_message, prefill="")

    def _call_api_json(self, system_prompt: str, user_message: str) -> str:
        """Structured cot/out call — prefill forces valid JSON and kills any
        preamble/chain-of-thought before the object."""
        return self._messages_create(system_prompt, user_message, prefill=self._PREFILL)

    def _messages_create(
        self, system_prompt: str, user_message: str, prefill: str
    ) -> str:
        messages: list = [{"role": "user", "content": user_message}]
        if prefill:
            messages.append({"role": "assistant", "content": prefill})

        response = self.client.messages.create(
            model=self.config.anthropic_model,
            max_tokens=self._MAX_TOKENS,
            system=system_prompt,
            messages=messages,
            temperature=0.4,
        )
        if response.stop_reason == "max_tokens":
            import logging

            logging.getLogger("bhai.llm").warning(
                "Claude response truncated (hit max_tokens=%d)", self._MAX_TOKENS
            )

        from anthropic.types import TextBlock

        block = next((b for b in response.content if isinstance(b, TextBlock)), None)
        text = block.text if block else ""
        # Re-attach the prefill so the parser sees the complete JSON object.
        return (prefill + text).strip()
