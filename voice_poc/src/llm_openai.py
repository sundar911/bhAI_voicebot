import re
from pathlib import Path
from typing import Dict, Any

from openai import OpenAI

from .config import Config, CONTEXT_DIR


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


class OpenAILLM:
    def __init__(self, config: Config, context_dir: Path = CONTEXT_DIR):
        self.config = config
        self.client = OpenAI(api_key=config.openai_api_key)
        self.context_dir = context_dir
        self.company_context = _read(context_dir / "company_context.md")
        self.escalation_policy = _read(context_dir / "escalation_policy.md")
        self.style_guide = _read(context_dir / "style_guide.md")

    def _system_prompt(self) -> str:
        return (
            "आप Tiny Miracles की सपोर्ट साथी हो। जवाब हमेशा गरमजोशी भरा, दोस्ताना और सम्मानजनक हो. "
            "सरल हिंदी (थोड़ा मराठी ठीक) में छोटा जवाब दो. "
            "जवाब हमेशा देवनागरी लिपि में लिखो। मुंबई की बोली जैसा सरल, रोज़मर्रा का हिंदी रखो; कठिन/तकनीकी शब्दों से बचो. "
            "नीचे दिए गए कॉन्टेक्स्ट से बाहर मत जाओ। यदि जानकारी नहीं है, तो साफ बोलो और इंसान को जोड़ने का विकल्प दो.\n\n"
            "Company Context:\n"
            f"{self.company_context}\n\n"
            "Escalation Policy:\n"
            f"{self.escalation_policy}\n\n"
            "Style Guide:\n"
            f"{self.style_guide}\n\n"
            "Rules:\n"
            "- Structure: 1) samajh aaya 2) answer 3) next step 4) offer escalation.\n"
            "- Hamesha short raho (20–40 sec voice-note length).\n"
            "- Sensitive topics ya doubt ho → offer escalation.\n"
            "- Hamesha last line mein likho 'ESCALATE: true' ya 'ESCALATE: false' (lowercase true/false).\n"
        )

    def _extract_text(self, response: Any) -> str:
        # New OpenAI Responses API has convenience output_text; fall back to manual extraction.
        if hasattr(response, "output_text") and response.output_text:
            return str(response.output_text).strip()

        collected = []
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                text_val = getattr(content, "text", None) or getattr(content, "value", None)
                if text_val:
                    collected.append(str(text_val))

        if not collected and hasattr(response, "choices"):
            choices = getattr(response, "choices", [])
            if choices:
                message = getattr(choices[0], "message", None)
                if message and hasattr(message, "content"):
                    collected.append(str(message.content))

        return "\n".join(collected).strip()

    def _detect_escalation(self, text: str) -> bool:
        match = re.search(r"ESCALATE\s*:\s*(true|false)", text, flags=re.IGNORECASE)
        if match:
            return match.group(1).lower() == "true"
        # fallback: look for keywords
        return "escalate" in text.lower()

    def generate(self, transcript: str) -> Dict[str, Any]:
        system_prompt = self._system_prompt()
        response = self.client.responses.create(
            model=self.config.openai_model,
            input=[
                {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
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

        cleaned_lines = [line for line in raw_text.splitlines() if "ESCALATE" not in line.upper()]
        cleaned_text = "\n".join([line.strip() for line in cleaned_lines if line.strip()]).strip()

        return {
            "text": cleaned_text or raw_text,
            "raw": raw_text,
            "escalate": escalate,
            "openai_response": response,
        }

