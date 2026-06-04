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

    # Token budget. With adaptive thinking on, this covers thinking + the
    # visible response — and thinking on a math-heavy turn (loan EMI
    # cross-impact, scheme eligibility walkthrough) can easily eat 1500-3000
    # tokens. 2048 was too tight (smoke test 2/3 truncated). 8192 leaves
    # comfortable headroom for both halves; Anthropic's adaptive-thinking
    # docs recommend 8000-16000 for production.
    _MAX_TOKENS = 8192

    # JSON schema for the structured reply, enforced via
    # `output_config.format`. Two required fields: `out` (the spoken reply,
    # which carries any in-body <memory> blocks and ESCALATE_CATEGORY line
    # that the downstream parser extracts) and `escalate` (boolean consent
    # gate for the email flow). Chain-of-thought goes into the model's
    # `thinking` block, NOT into this object.
    _RESPONSE_SCHEMA: dict = {
        "type": "object",
        "properties": {
            "out": {
                "type": "string",
                "description": (
                    "The message the user hears, in the user's language "
                    "(Hindi in Devanagari by default). Goes straight to TTS "
                    "after stripping <memory>...</memory> blocks and any "
                    "ESCALATE_CATEGORY: line."
                ),
            },
            "escalate": {
                "type": "boolean",
                "description": (
                    "True ONLY when the user has explicitly consented to "
                    "emailing the impact team on this turn. Default false."
                ),
            },
        },
        "required": ["out", "escalate"],
        "additionalProperties": False,
    }

    def _call_api(self, system_prompt: str, user_message: str) -> str:
        """Plain call — NO structured-output enforcement.

        Used by callers that expect free-form text (summarizer, nudges).
        These must NOT be forced into the JSON envelope, or their output
        gets corrupted (and, for nudges, leaks JSON straight to the user).
        """
        return self._messages_create(system_prompt, user_message, structured=False)

    def _call_api_json(self, system_prompt: str, user_message: str) -> str:
        """Structured {out, escalate} call.

        Uses `output_config.format` (Anthropic GA 2026-02-04) to enforce
        the JSON schema via grammar-constrained decoding, and adaptive
        thinking for chain-of-thought separation (the thinking block is
        returned alongside the JSON text block and never reaches TTS).

        Replaces the legacy assistant-prefill approach, which Sonnet 4.6
        rejects with `400: This model does not support assistant message
        prefill` — extended thinking and prefill are mutually exclusive.
        """
        return self._messages_create(system_prompt, user_message, structured=True)

    def _messages_create(
        self, system_prompt: str, user_message: str, structured: bool
    ) -> str:
        messages: list = [{"role": "user", "content": user_message}]

        # When web_search is enabled, pass the Anthropic server-side tool so
        # the model can ground specifics it doesn't know (local clinics, "box
        # cricket near Grant Road", etc.). Anthropic executes the search
        # server-side and merges results into the response — no client-side
        # tool_use loop needed. max_uses enforced server-side. Coexists
        # cleanly with `output_config.format` (verified by
        # scripts/spike_structured_output.py on 2026-06-04).
        kwargs: dict = {
            "model": self.config.anthropic_model,
            "max_tokens": self._MAX_TOKENS,
            "system": system_prompt,
            "messages": messages,
            # Adaptive thinking (structured path) requires temperature=1.
            # The plain path keeps a lower temperature for tighter free-form
            # output (summarizer/nudges).
            "temperature": 1.0 if structured else 0.4,
        }
        if self.config.web_search_enabled:
            kwargs["tools"] = [
                {
                    "type": self.config.web_search_tool_name,
                    "name": "web_search",
                    "max_uses": self.config.web_search_max_uses_per_call,
                }
            ]

        # Structured path: schema enforcement + adaptive thinking. Both
        # passed via `extra_body` because anthropic-python 0.84 doesn't
        # surface these params as first-class kwargs yet; the SDK forwards
        # the dict verbatim into the request body.
        if structured:
            kwargs["extra_body"] = {
                "output_config": {
                    "format": {
                        "type": "json_schema",
                        "schema": self._RESPONSE_SCHEMA,
                    }
                },
                "thinking": {"type": "adaptive"},
            }

        response = self.client.messages.create(**kwargs)

        if response.stop_reason == "max_tokens":
            import logging

            logging.getLogger("bhai.llm").warning(
                "Claude response truncated (hit max_tokens=%d)", self._MAX_TOKENS
            )

        # Concatenate ALL TextBlocks. With web_search, the model can emit
        # multiple text segments interleaved with server_tool_use,
        # web_search_tool_result, and thinking blocks; the structured-output
        # JSON lands in the FINAL text block (after every search resolves),
        # so concatenating all text blocks with a newline is safe — newlines
        # are valid JSON whitespace between/inside the object.
        from anthropic.types import TextBlock

        text_parts = [b.text for b in response.content if isinstance(b, TextBlock)]
        return "\n".join(text_parts).strip()
