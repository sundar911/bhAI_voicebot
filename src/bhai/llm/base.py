"""
Abstract base class for LLM backends.
All LLM implementations should inherit from this class.

Shared logic: knowledge-base loading, system-prompt construction,
escalation detection, emotion parsing, and response cleanup live here.
Subclasses only implement _call_api() and model_name.
"""

import json
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import KNOWLEDGE_BASE_DIR, Config
from ..resilience.retry import retry_with_backoff


def _read_file(path: Path) -> str:
    """Read file contents, return empty string if not found."""
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return ""


EMOTION_INSTRUCTION = (
    "\n=== Emotion Annotation ===\n"
    "After your main response (and the ESCALATE line), add one final line:\n"
    'EMOTIONS_JSON: [{"text": "segment text", "emotion": "neutral"}, ...]\n'
    "Split your response into short segments (4-8 words each).\n"
    "Valid emotions: excited, whisper, sigh, sad, laugh, pause, neutral\n"
    "Use 'neutral' for most segments. Only add emotion when genuinely "
    "appropriate to bhAI's warm, empathetic personality.\n"
)


class BaseLLM(ABC):
    """
    Abstract base class for LLM backends.

    Implementations only need to override:
    - _call_api(system_prompt, user_message) -> str
    - model_name property
    """

    def __init__(
        self,
        config: Config,
        knowledge_base_dir: Optional[Path] = None,
    ):
        self.config = config
        self.kb_dir = knowledge_base_dir or KNOWLEDGE_BASE_DIR

        # Load shared context
        shared_dir = self.kb_dir / "shared"
        self.company_overview = _read_file(shared_dir / "company_overview.md")
        self.escalation_policy = _read_file(shared_dir / "escalation_policy.md")
        self.style_guide = _read_file(shared_dir / "style_guide.md")

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier for logging."""
        pass

    @abstractmethod
    def _call_api(self, system_prompt: str, user_message: str) -> str:
        """
        Make the LLM API call and return the raw response text.

        This is the only method subclasses must implement.
        """
        pass

    # ── knowledge base ────────────────────────────────────────────────────

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

    # ── user profiles ────────────────────────────────────────────────────

    def load_user_profile(self, phone: str) -> str:
        """Load and decrypt user profile from knowledge_base/users/{phone}.md."""
        from ..security.crypto import decrypt_text

        profile_path = self.kb_dir / "users" / f"{phone}.md"
        raw = _read_file(profile_path)
        if not raw:
            return ""
        try:
            return decrypt_text(raw)
        except Exception:
            return raw  # fallback for plaintext profiles (_template.md, manual)

    # ── prompt construction ───────────────────────────────────────────────

    # ── prompt loading (version-switchable via PROMPT_VERSION env var) ────

    _PROMPTS_DIR = Path(__file__).parent / "prompts"
    _prompt_cache: Dict[str, str] = {}

    @classmethod
    def _load_prompt_template(cls, version: str) -> str:
        """Load prompt template from prompts/{version}.md with caching."""
        if version in cls._prompt_cache:
            return cls._prompt_cache[version]

        path = cls._PROMPTS_DIR / f"{version}.md"
        if not path.exists():
            raise FileNotFoundError(
                f"Prompt version '{version}' not found at {path}. "
                f"Available: {[p.stem for p in cls._PROMPTS_DIR.glob('*.md')]}"
            )
        content = path.read_text(encoding="utf-8").strip()
        cls._prompt_cache[version] = content
        return content

    def _build_system_prompt(
        self,
        domain: str,
        user_profile: str = "",
        memory_summary: str = "",
        extracted_facts: str = "",
    ) -> str:
        """Build system prompt from versioned template + user context + KB."""
        version = getattr(self.config, "prompt_version", "current")
        prompt = self._load_prompt_template(version)

        # Inject knowledge base: helpdesk (documents) + hr_admin (yojanas)
        helpdesk_kb = self._load_domain_context("helpdesk")
        if helpdesk_kb:
            prompt += f"\n\n=== Helpdesk Knowledge Base (documents, IDs) ===\n{helpdesk_kb}"

        govt_schemes = _read_file(self.kb_dir / "hr_admin" / "govt_schemes.md")
        if govt_schemes:
            prompt += f"\n\n=== Government Schemes (Yojanas) Knowledge Base ===\n{govt_schemes}"

        # Append user-specific context (only if available)
        if user_profile:
            prompt += f"\n\n=== User Profile ===\n{user_profile}"

        if memory_summary:
            prompt += f"\n\n=== पिछली बातचीत का सारांश ===\n{memory_summary}"

        if extracted_facts:
            prompt += f"\n\n=== याद रखी हुई बातें ===\n{extracted_facts}"

        return prompt

    # ── Topic tracking for conversation switching ─────────────────────

    # Keywords that signal each topic category
    _TOPIC_KEYWORDS = {
        "खाना": {"वड़ा", "पाव", "भाजी", "खाना", "खाती", "खाते", "ठेला", "चाय",
                  "चीज़", "घी", "recipe", "बनाता", "बनाती", "पीती", "पीते",
                  "सरदार", "favourite", "dish", "food", "भूख", "नाश्ता", "बिरयानी"},
        "मुंबई": {"लोकल", "ट्रेन", "भीड़", "ऑटो", "मीटर", "station", "स्टेशन",
                  "किलोमीटर", "ट्रैफ़िक", "बारिश", "मुंबई", "धारावी"},
        "काम": {"बैग", "design", "बना", "बनाती", "order", "काम", "office",
                "product", "pattern", "हाथ", "machine", "शिफ्ट"},
        "मौसम": {"गर्मी", "बारिश", "सर्दी", "धूप", "मौसम", "पानी", "भीगना", "ठंड"},
        "Bollywood": {"गाना", "शाहरुख़", "फ़िल्म", "actor", "actress", "Bollywood",
                      "गाती", "गाते"},
        "परिवार": {"बेटा", "बेटी", "school", "बच्चे", "शरारत", "prize", "पढ़ाई",
                   "बीवी", "पति", "घर", "परिवार", "माँ", "पापा", "भाई"},
        "ज़िंदगी": {"Sunday", "छुट्टी", "plan", "ख़ुशी", "याद", "सुबह", "superpower",
                    "सपना", "इंसान"},
    }

    @staticmethod
    def _detect_topic(text: str) -> str:
        """Detect the dominant topic from text using keyword matching."""
        text_lower = text.lower()
        best_topic = "other"
        best_score = 0
        for topic, keywords in BaseLLM._TOPIC_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw.lower() in text_lower)
            if score > best_score:
                best_score = score
                best_topic = topic
        return best_topic if best_score > 0 else "other"

    @staticmethod
    def _count_same_topic_turns(
        conversation_history: List[Dict[str, str]],
    ) -> tuple:
        """Count consecutive same-topic turns from the end. Returns (topic, count)."""
        if not conversation_history:
            return ("other", 0)

        # Look at last N messages (both user + assistant)
        recent = conversation_history[-8:]
        current_topic = BaseLLM._detect_topic(
            " ".join(m["content"] for m in recent[-2:])  # last exchange
        )

        count = 0
        for msg in reversed(recent):
            msg_topic = BaseLLM._detect_topic(msg["content"])
            if msg_topic == current_topic or msg_topic == "other":
                count += 1
            else:
                break
        return (current_topic, count)

    # Topic suggestions mapped to what to switch TO given current topic
    _TOPIC_TRANSITIONS = {
        "खाना": ["कहाँ रहते हो/इलाक़ा", "office कैसे जाते हो", "Bollywood गाना"],
        "मुंबई": ["परिवार/घर में कौन-कौन", "काम कैसा चल रहा", "खाना"],
        "काम": ["परिवार/बच्चे", "कहाँ रहते हो", "Sunday plan"],
        "मौसम": ["काम कैसा चल रहा", "खाना", "कहाँ रहते हो"],
        "Bollywood": ["Sunday plan", "परिवार", "खाना"],
        "परिवार": ["Bollywood", "Sunday plan", "खाना"],
        "ज़िंदगी": ["परिवार", "काम", "खाना"],
        "other": ["खाना — क्या पसंद है", "कहाँ रहते हो", "office कैसे जाते हो"],
    }

    @staticmethod
    def _build_user_message(
        transcript: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        is_new_session: bool = False,
    ) -> str:
        """Build the user message with conversation history and topic-switch injection."""
        parts = []

        # Include recent conversation history for multi-turn context
        if conversation_history:
            parts.append("=== Recent Conversation ===")
            for msg in conversation_history:
                role_label = "User" if msg["role"] == "user" else "भाई"
                parts.append(f"{role_label}: {msg['content']}")
            parts.append("=== End Recent Conversation ===\n")

            # Topic tracker: detect staleness and suggest switch
            topic, turn_count = BaseLLM._count_same_topic_turns(conversation_history)
            if topic != "other" and turn_count >= 6:
                alternatives = BaseLLM._TOPIC_TRANSITIONS.get(topic, ["कुछ नया"])
                alt_str = ", ".join(alternatives[:2])
                parts.append(
                    f"[सुझाव: \"{topic}\" पर काफ़ी बात हो चुकी है। "
                    f"अगर user ने छोटा जवाब दिया है तो smoothly topic बदलो — "
                    f"\"अच्छा एक बात बताओ —\" बोलो और {alt_str} में से कुछ पूछो। "
                    f"पर अगर user अभी detail दे रहा है तो उनकी बात सुनो।]\n"
                )

        if is_new_session:
            parts.append(
                "(नई बातचीत शुरू हो रही है — गरमजोशी से बात कर, "
                "पिछली बातों का हवाला दे अगर याद में है।)\n"
            )

        parts.append(
            "User का voice message (हिंदी/मराठी)। "
            "देवनागरी में जवाब दो। छोटा रखो।\n\n"
            f"User: {transcript}"
        )

        return "\n".join(parts)

    # ── response parsing ──────────────────────────────────────────────────

    @staticmethod
    def _detect_escalation(text: str) -> bool:
        """Detect if response indicates need for escalation."""
        match = re.search(r"ESCALATE\s*:\s*(true|false)", text, flags=re.IGNORECASE)
        if match:
            return match.group(1).lower() == "true"
        return "escalate" in text.lower()

    @staticmethod
    def _clean_response(raw_text: str, strip_emotions: bool = False) -> str:
        """Remove ESCALATE/EMOTIONS_JSON lines and strip markdown formatting.

        Markdown leaks (asterisks, bullet markers) get read literally by TTS
        ("asterisk asterisk", "dash"). We strip them as a safety net even
        though the prompt also forbids them.
        """
        cleaned_lines = []
        for line in raw_text.splitlines():
            if "ESCALATE" in line.upper():
                continue
            if strip_emotions and line.strip().startswith("EMOTIONS_JSON:"):
                continue
            stripped = line.strip()
            if stripped:
                cleaned_lines.append(stripped)
        text = "\n".join(cleaned_lines).strip()
        return BaseLLM._strip_markdown(text)

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """Strip markdown so TTS doesn't read it literally.

        Devanagari Hindi text never contains asterisks/backticks, so we
        can safely scrub them. Leading bullet/numbered list markers and
        markdown headings are also stripped.
        """
        if not text:
            return text
        # Headings: # foo, ## foo, ### foo
        text = re.sub(r"^#+\s+", "", text, flags=re.MULTILINE)
        # Bullet markers at line start: -, *, • (only at start, not mid-sentence dashes)
        text = re.sub(r"^[ \t]*[-*•]\s+", "", text, flags=re.MULTILINE)
        # Numbered list markers: "1. foo", "2) foo"
        text = re.sub(r"^[ \t]*\d+[\.\)]\s+", "", text, flags=re.MULTILINE)
        # Horizontal rules: ---, ___, ***
        text = re.sub(r"^[\s]*[-_*]{3,}[\s]*$", "", text, flags=re.MULTILINE)
        # All remaining asterisks (used for **bold** / *italic*) — Hindi text has none
        text = text.replace("*", "")
        # Backticks (code formatting)
        text = text.replace("`", "")
        # Multiple consecutive underscores (markdown emphasis)
        text = re.sub(r"_{2,}", "", text)
        # Collapse leftover blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _parse_emotion_segments(raw_text: str) -> Optional[List[dict]]:
        """Extract EMOTIONS_JSON line from raw LLM output and parse it."""
        for line in raw_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("EMOTIONS_JSON:"):
                json_str = stripped[len("EMOTIONS_JSON:") :].strip()
                try:
                    segments = json.loads(json_str)
                    if isinstance(segments, list) and all(
                        isinstance(s, dict) and "text" in s for s in segments
                    ):
                        return segments
                except (json.JSONDecodeError, TypeError):
                    pass
        return None

    # ── retry helper ─────────────────────────────────────────────────────

    def _call_api_with_retry(
        self, system_prompt: str, user_message: str, max_attempts: int = 3
    ) -> str:
        """Call _call_api with retry and exponential backoff."""
        return retry_with_backoff(
            self._call_api,
            system_prompt,
            user_message,
            max_attempts=max_attempts,
            base_delay=1.0,
            max_delay=10.0,
        )

    # ── public API ────────────────────────────────────────────────────────

    def generate(
        self,
        transcript: str,
        domain: str = "hr_admin",
        user_profile: str = "",
        memory_summary: str = "",
        extracted_facts: str = "",
        conversation_history: Optional[List[Dict[str, str]]] = None,
        is_new_session: bool = False,
    ) -> Dict[str, Any]:
        """
        Generate a response for the given transcript with full context.

        Args:
            transcript: User's transcribed speech
            domain: Knowledge domain (hr_admin, helpdesk, production)
            user_profile: User's profile text from knowledge base
            memory_summary: Rolling conversation summary
            extracted_facts: Bullet list of remembered facts
            conversation_history: Recent messages for multi-turn context
            is_new_session: Whether this is a new conversation session

        Returns:
            Dictionary with text, raw, and escalate.
        """
        system_prompt = self._build_system_prompt(
            domain, user_profile, memory_summary, extracted_facts
        )
        user_message = self._build_user_message(
            transcript, conversation_history, is_new_session
        )
        raw_text = self._call_api_with_retry(system_prompt, user_message)

        escalate = self._detect_escalation(raw_text)
        cleaned_text = self._clean_response(raw_text)

        return {
            "text": cleaned_text or raw_text,
            "raw": raw_text,
            "escalate": escalate,
        }

    def generate_with_emotions(
        self,
        transcript: str,
        domain: str = "hr_admin",
        user_profile: str = "",
        memory_summary: str = "",
        extracted_facts: str = "",
        conversation_history: Optional[List[Dict[str, str]]] = None,
        is_new_session: bool = False,
        mode_instruction: str = "",
    ) -> Dict[str, Any]:
        """
        Generate response with per-segment emotion annotations and full context.

        `mode_instruction` is an extra block appended to the system prompt for
        one-off behaviours (re-onboarding on /start, etc.) without forking the
        whole prompt template. Pass empty string for default behaviour.

        Falls back to a single neutral segment if parsing fails.
        Returns dict with text, raw, escalate, and segments.
        """
        system_prompt = (
            self._build_system_prompt(
                domain, user_profile, memory_summary, extracted_facts
            )
            + EMOTION_INSTRUCTION
        )
        if mode_instruction:
            system_prompt += "\n\n" + mode_instruction
        user_message = self._build_user_message(
            transcript, conversation_history, is_new_session
        )
        raw_text = self._call_api_with_retry(system_prompt, user_message)

        escalate = self._detect_escalation(raw_text)
        cleaned_text = self._clean_response(raw_text, strip_emotions=True)

        segments = self._parse_emotion_segments(raw_text)
        if segments is None:
            segments = [{"text": cleaned_text or raw_text, "emotion": "neutral"}]

        return {
            "text": cleaned_text or raw_text,
            "raw": raw_text,
            "escalate": escalate,
            "segments": segments,
        }
