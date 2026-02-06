"""
OpenAI LLM backend implementation.
Uses OpenAI's API for response generation with knowledge base context.
"""

import re
from pathlib import Path
from typing import Any, Dict, Optional

from openai import OpenAI

from ..config import Config, KNOWLEDGE_BASE_DIR
from .base import BaseLLM


def _read_file(path: Path) -> str:
    """Read file contents, return empty string if not found."""
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return ""


class OpenAILLM(BaseLLM):
    """
    OpenAI LLM backend for response generation.

    Loads knowledge base context and generates contextually
    grounded responses in Hindi with escalation detection.
    """

    def __init__(
        self,
        config: Config,
        knowledge_base_dir: Optional[Path] = None
    ):
        """
        Initialize OpenAI LLM.

        Args:
            config: Application configuration with API keys
            knowledge_base_dir: Path to knowledge base (default: project knowledge_base/)
        """
        self.config = config
        self.client = OpenAI(api_key=config.openai_api_key)
        self.kb_dir = knowledge_base_dir or KNOWLEDGE_BASE_DIR

        # Load shared context
        shared_dir = self.kb_dir / "shared"
        self.company_overview = _read_file(shared_dir / "company_overview.md")
        self.escalation_policy = _read_file(shared_dir / "escalation_policy.md")
        self.style_guide = _read_file(shared_dir / "style_guide.md")

    @property
    def model_name(self) -> str:
        return self.config.openai_model

    def _load_domain_context(self, domain: str) -> str:
        """Load domain-specific knowledge base content."""
        domain_dir = self.kb_dir / domain
        if not domain_dir.exists():
            return ""

        context_parts = []
        for md_file in sorted(domain_dir.glob("*.md")):
            content = _read_file(md_file)
            if content:
                context_parts.append(f"### {md_file.stem}\n{content}")

        return "\n\n".join(context_parts)

    def _build_system_prompt(self, domain: str) -> str:
        """Build system prompt with shared and domain-specific context."""
        domain_context = self._load_domain_context(domain)

        return (
            "आप Tiny Miracles की सपोर्ट साथी हो। जवाब हमेशा गरमजोशी भरा, दोस्ताना और सम्मानजनक हो. "
            "सरल हिंदी (थोड़ा मराठी ठीक) में छोटा जवाब दो. "
            "जवाब हमेशा देवनागरी लिपि में लिखो। मुंबई की बोली जैसा सरल, रोज़मर्रा का हिंदी रखो; कठिन/तकनीकी शब्दों से बचो. "
            "नीचे दिए गए कॉन्टेक्स्ट से बाहर मत जाओ। यदि जानकारी नहीं है, तो साफ बोलो और इंसान को जोड़ने का विकल्प दो.\n\n"
            "=== Company Overview ===\n"
            f"{self.company_overview}\n\n"
            f"=== {domain.upper()} Domain Knowledge ===\n"
            f"{domain_context}\n\n"
            "=== Escalation Policy ===\n"
            f"{self.escalation_policy}\n\n"
            "=== Style Guide ===\n"
            f"{self.style_guide}\n\n"
            "=== Response Rules ===\n"
            "- Structure: 1) samajh aaya 2) answer 3) next step 4) offer escalation.\n"
            "- Hamesha short raho (20-40 sec voice-note length).\n"
            "- Sensitive topics ya doubt ho → offer escalation.\n"
            "- Hamesha last line mein likho 'ESCALATE: true' ya 'ESCALATE: false' (lowercase true/false).\n"
        )

    def _extract_text(self, response: Any) -> str:
        """Extract text from OpenAI response object."""
        # New Responses API has output_text
        if hasattr(response, "output_text") and response.output_text:
            return str(response.output_text).strip()

        # Fallback for various response formats
        collected = []
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                text_val = getattr(content, "text", None) or getattr(content, "value", None)
                if text_val:
                    collected.append(str(text_val))

        # Chat completions format
        if not collected and hasattr(response, "choices"):
            choices = getattr(response, "choices", [])
            if choices:
                message = getattr(choices[0], "message", None)
                if message and hasattr(message, "content"):
                    collected.append(str(message.content))

        return "\n".join(collected).strip()

    def _detect_escalation(self, text: str) -> bool:
        """Detect if response indicates need for escalation."""
        match = re.search(r"ESCALATE\s*:\s*(true|false)", text, flags=re.IGNORECASE)
        if match:
            return match.group(1).lower() == "true"
        # Fallback: look for keywords
        return "escalate" in text.lower()

    def generate(self, transcript: str, domain: str = "hr_admin") -> Dict[str, Any]:
        """
        Generate response for transcript using domain context.

        Args:
            transcript: User's transcribed speech
            domain: Knowledge domain (hr_admin, helpdesk, production)

        Returns:
            Dictionary with text, raw, escalate, and openai_response
        """
        system_prompt = self._build_system_prompt(domain)

        response = self.client.responses.create(
            model=self.config.openai_model,
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}]
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Transcribed user audio (Hindi/Marathi mix). "
                                "Reply in Hindi. Keep it short.\n\n"
                                f"User said: {transcript}"
                            ),
                        }
                    ],
                },
            ],
            temperature=0.4,
        )

        raw_text = self._extract_text(response)
        escalate = self._detect_escalation(raw_text)

        # Remove ESCALATE marker from user-facing text
        cleaned_lines = [
            line for line in raw_text.splitlines()
            if "ESCALATE" not in line.upper()
        ]
        cleaned_text = "\n".join(
            [line.strip() for line in cleaned_lines if line.strip()]
        ).strip()

        return {
            "text": cleaned_text or raw_text,
            "raw": raw_text,
            "escalate": escalate,
            "openai_response": response,
        }
