"""
Sarvam AI LLM backend implementation.
Uses Sarvam's OpenAI-compatible chat completions API.
"""

from pathlib import Path
from typing import Optional

from openai import OpenAI

from ..config import Config
from .base import BaseLLM


class SarvamLLM(BaseLLM):
    """Sarvam AI LLM backend via OpenAI-compatible API."""

    def __init__(
        self,
        config: Config,
        knowledge_base_dir: Optional[Path] = None,
    ):
        super().__init__(config, knowledge_base_dir)
        if not config.sarvam_api_key:
            raise RuntimeError(
                "SARVAM_API_KEY required when llm_backend='sarvam'. "
                "Set it in environment or .env."
            )
        self.client = OpenAI(
            base_url=config.sarvam_llm_url,
            api_key=config.sarvam_api_key,
        )

    @property
    def model_name(self) -> str:
        return self.config.sarvam_llm_model

    def _call_api(self, system_prompt: str, user_message: str) -> str:
        prompt_chars = len(system_prompt) + len(user_message)
        print(
            f"[Sarvam LLM] Prompt size: ~{prompt_chars} chars, "
            f"model: {self.config.sarvam_llm_model}"
        )

        response = self.client.chat.completions.create(
            model=self.config.sarvam_llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.4,
            max_tokens=2048,
        )

        usage = getattr(response, "usage", None)
        if usage:
            print(
                f"[Sarvam LLM] Tokens — prompt: {usage.prompt_tokens}, "
                f"completion: {usage.completion_tokens}, "
                f"total: {usage.total_tokens}"
            )

        content = response.choices[0].message.content
        if not content:
            raise RuntimeError(
                f"Sarvam LLM returned empty response. "
                f"Model: {self.config.sarvam_llm_model}, "
                f"finish_reason: {response.choices[0].finish_reason}"
            )
        return content.strip()
