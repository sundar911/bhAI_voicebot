"""
OpenAI LLM backend implementation.
Uses OpenAI's Responses API for inference.
"""

from pathlib import Path
from typing import Any, Dict, Optional

from openai import OpenAI

from ..config import Config
from .base import BaseLLM


class OpenAILLM(BaseLLM):
    """OpenAI LLM backend using the Responses API."""

    def __init__(
        self,
        config: Config,
        knowledge_base_dir: Optional[Path] = None,
    ):
        super().__init__(config, knowledge_base_dir)
        if not config.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY required when llm_backend='openai'. "
                "Set it in environment or .env."
            )
        self.client = OpenAI(api_key=config.openai_api_key)

    @property
    def model_name(self) -> str:
        return self.config.openai_model

    # Native structured-output schema for the cot/out contract. ``strict`` +
    # explicit property order (cot before out) guarantees valid JSON where the
    # reasoning is generated before — and so conditions — the reply.
    _JSON_SCHEMA = {
        "type": "json_schema",
        "name": "bhai_reply",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "cot": {"type": "string"},
                "out": {"type": "string"},
                "escalate": {"type": "boolean"},
            },
            "required": ["cot", "out", "escalate"],
            "additionalProperties": False,
        },
    }

    def _call_api(self, system_prompt: str, user_message: str) -> str:
        """Plain free-form call (summarizer, nudges build their own prompts)."""
        return self._respond(system_prompt, user_message, json_format=None)

    def _call_api_json(self, system_prompt: str, user_message: str) -> str:
        """Structured cot/out call with native json_schema enforcement."""
        return self._respond(
            system_prompt, user_message, json_format={"format": self._JSON_SCHEMA}
        )

    def _respond(
        self,
        system_prompt: str,
        user_message: str,
        json_format: Optional[Dict[str, Any]],
    ) -> str:
        kwargs: Dict[str, Any] = dict(
            model=self.config.openai_model,
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": user_message}],
                },
            ],
            temperature=0.4,
        )
        if json_format is not None:
            kwargs["text"] = json_format

        response = self.client.responses.create(**kwargs)
        return self._extract_text(response)

    @staticmethod
    def _extract_text(response: Any) -> str:
        """Extract text from OpenAI response object."""
        if hasattr(response, "output_text") and response.output_text:
            return str(response.output_text).strip()

        collected = []
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                text_val = getattr(content, "text", None) or getattr(
                    content, "value", None
                )
                if text_val:
                    collected.append(str(text_val))

        if not collected and hasattr(response, "choices"):
            choices = getattr(response, "choices", [])
            if choices:
                message = getattr(choices[0], "message", None)
                if message and hasattr(message, "content"):
                    collected.append(str(message.content))

        return "\n".join(collected).strip()
