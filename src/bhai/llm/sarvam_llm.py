"""
Sarvam AI LLM backend implementation.
Uses Sarvam's OpenAI-compatible chat completions API.
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from openai import OpenAI

from ..config import Config
from .base import BaseLLM

logger = logging.getLogger("bhai.llm")


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
        """Plain free-form call (summarizer, nudges build their own prompts)."""
        return self._chat(system_prompt, user_message, json_mode=False)

    def _call_api_json(self, system_prompt: str, user_message: str) -> str:
        """Structured cot/out call with native JSON-object enforcement.

        Uses the OpenAI-compatible ``response_format={"type": "json_object"}``.
        If the endpoint rejects it (older/limited servers), degrades gracefully
        to the plain call — the prompt instruction + tolerant parser still
        produce valid cot/out in that case.
        """
        try:
            return self._chat(system_prompt, user_message, json_mode=True)
        except Exception as e:  # noqa: BLE001 — compatibility shim, retry plain
            logger.warning(
                "Sarvam json_object mode failed (%s); falling back to "
                "instruction-only.",
                e,
            )
            return self._chat(system_prompt, user_message, json_mode=False)

    def _chat(self, system_prompt: str, user_message: str, json_mode: bool) -> str:
        prompt_chars = len(system_prompt) + len(user_message)
        print(
            f"[Sarvam LLM] Prompt size: ~{prompt_chars} chars, "
            f"model: {self.config.sarvam_llm_model}, json_mode={json_mode}"
        )

        kwargs: Dict[str, Any] = dict(
            model=self.config.sarvam_llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.4,
            max_tokens=2048,
            frequency_penalty=0.6,
            presence_penalty=0.4,
        )
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = self.client.chat.completions.create(**kwargs)

        usage = getattr(response, "usage", None)
        if usage:
            print(
                f"[Sarvam LLM] Tokens — prompt: {usage.prompt_tokens}, "
                f"completion: {usage.completion_tokens}, "
                f"total: {usage.total_tokens}"
            )

        if response.choices[0].finish_reason in ("length", "max_tokens"):
            logger.warning(
                "Sarvam response truncated (finish_reason=%s)",
                response.choices[0].finish_reason,
            )

        content = response.choices[0].message.content
        if not content:
            raise RuntimeError(
                f"Sarvam LLM returned empty response. "
                f"Model: {self.config.sarvam_llm_model}, "
                f"finish_reason: {response.choices[0].finish_reason}"
            )
        return content.strip()
