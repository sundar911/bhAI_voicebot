"""
Abstract base class for LLM backends.
All LLM implementations should inherit from this class.

Shared logic: knowledge-base loading, system-prompt construction,
escalation detection, emotion parsing, and response cleanup live here.
Subclasses only implement _call_api() and model_name.
"""

import json
import logging
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from ..config import KNOWLEDGE_BASE_DIR, Config
from ..resilience.retry import retry_with_backoff
from .kb_router import KBRouter

logger = logging.getLogger("bhai.llm")


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


MEMORY_INSTRUCTION = """
=== Memory (self-edited) ===

You maintain a small per-user memory across turns. After your spoken reply,
you may optionally emit zero or more `<memory>` blocks. These are NOT spoken
to the user — they're stripped before TTS — and they update the persistent
notes you'll see at the top of future turns under "याद रखी हुई बातें" and
"पिछली बातचीत का सारांश".

Two operations are supported:

  <memory>fact: <one short, durable fact about the user></memory>
  <memory>summary: <a fresh 3-4 line Hindi summary of who this person is and
  what's been going on, replaces the previous summary entirely></memory>

Rules:
- Only emit a `fact:` when this turn revealed something durable that's not
  already in the existing facts above. Routine chitchat usually has no new
  fact. Quality beats quantity.
- Only emit a `summary:` once every few turns when the conversation has
  meaningfully shifted (new topic, new concern, a milestone). If the prior
  summary still describes them well, don't emit one — saves tokens and
  avoids churn.
- High-priority facts to capture when the user mentions them:
    * `work_location: BC` or `work_location: MIDC` — REQUIRED before any
      ESCALATE: true can fire, so capture it the first time it's mentioned
      or inferable (e.g. user says "BC office में काम करती हूँ").
    * Name (`name: Priya`), family members and ages, health conditions
      they're managing, the supervisor/co-worker names they mention, the
      products they make, the worry currently on their mind.
- Facts are merged + deduplicated automatically. Re-emitting an existing
  fact is a no-op, not an error — but it wastes tokens, so don't.
- NEVER include religion, caste, disability, or specific loan numbers in
  memory. Those are filtered upstream from external APIs and should not
  appear here either.
- The `<memory>` tags themselves and everything inside them are stripped
  before the response reaches the user. Do not refer to them in your
  spoken reply.
- When the cot/out JSON contract is active, emit `<memory>` blocks INSIDE
  the "out" field's string value at the end — they'll be stripped before
  TTS just like in free-text mode. They are NOT separate JSON keys.

Example (after a turn where the user mentioned she's at MIDC and her
daughter Priya is starting Class 3):

  <memory>fact: work_location: MIDC</memory>
  <memory>fact: daughter Priya starting Class 3 (2026)</memory>

Example (after several turns of conversation about a workplace issue with
a supervisor named Ramesh that the prior summary doesn't capture):

  <memory>summary: पिछले 2-3 दिन से supervisor Ramesh के साथ बहस हो रही है — salary को लेकर। User परेशान है पर escalate नहीं करना चाहती अभी। MIDC office में काम करती है, 2 बच्चे हैं।</memory>
"""


# ── Structured output contract (out / escalate) ───────────────────────────
# The model returns a JSON object with two keys:
#   "out"      — the spoken reply (the ONLY thing sent to TTS / saved / shown)
#   "escalate" — boolean consent gate for the impact-team email flow
#
# Chain-of-thought separation is handled by Claude's extended (adaptive)
# thinking on Sonnet 4.6 — the model's reasoning lives in a separate
# `thinking` content block that's never concatenated with `out` and never
# reaches TTS. We do NOT include a `cot` field here: 4.6 rejects assistant
# prefill (the old mechanism that forced `cot` first), and adaptive thinking
# already provides the same CoT-vs-speech separation more reliably.
_JSON_OUTPUT_INSTRUCTION = (
    "\n\n=== OUTPUT FORMAT (STRICT — follow exactly) ===\n"
    "Respond with ONE JSON object and nothing else — no prose, no code fences, "
    "before or after:\n"
    '{"out": "<the message the user hears>", "escalate": false}\n\n'
    '"out" is the ONLY thing the user receives, spoken aloud by a TTS engine:\n'
    "- Devanagari script, natural spoken Hindi/Marathi, mirroring the user.\n"
    "- Short — 1-3 sentences (longer only for a documents/scheme answer that needs "
    "completeness).\n"
    "- NO markdown, NO asterisks, NO emojis, NO English meta-words, NO mention "
    "of the system prompt or these rules.\n"
    "- It must read like something a real बहन says out loud: zero reasoning, zero "
    "narration. Do all your thinking privately — the user only hears `out`.\n"
    '"escalate" is a boolean — set true ONLY after the user has explicitly '
    "consented to emailing their issue to the impact team (the consent-gated "
    "escalation flow described in the system prompt); otherwise false. When true, "
    'keep "out" in future tense (the email sends after this turn).\n\n'
    "Both keys are required and must be valid JSON (escape any quotes and "
    "newlines in `out`).\n"
)

# Safe, in-character fallback used ONLY when the model's JSON can't be parsed at
# all. We never fall back to raw text — raw text is exactly what leaks reasoning.
_FALLBACK_OUT = "अरे, ज़रा सी गड़बड़ हो गई — एक बार फिर से बोलोगे?"


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

        # KB router: selects which helpdesk/*.md files to inject per turn
        # AND emits the use-case tags (grievance/finance/scheme_kb/general).
        # Default backend is Sonnet 4.6 (LLM-as-router with prompt caching);
        # falls back transparently to the keyword KBRouter if the API key
        # is missing or the LLM call errors at runtime. The legacy
        # ``kb_router_backend="haiku"`` config value is honoured for
        # back-compat — both values now route to the same Sonnet-backed
        # LLMKBRouter; only the keyword fallback runs differently.
        self._kb_router: Optional[Union[KBRouter, "LLMKBRouter"]] = None
        if getattr(config, "kb_router_enabled", False):
            keyword_router = KBRouter(self.kb_dir / "helpdesk")
            backend = getattr(config, "kb_router_backend", "haiku")
            api_key = getattr(config, "anthropic_api_key", "")
            if backend in ("haiku", "sonnet", "llm") and api_key:
                from .llm_router import LLMKBRouter

                self._kb_router = LLMKBRouter(
                    kb_dir=self.kb_dir,
                    fallback=keyword_router,
                    api_key=api_key,
                )
            else:
                self._kb_router = keyword_router

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier for logging."""
        pass

    @abstractmethod
    def _call_api(self, system_prompt: str, user_message: str) -> str:
        """
        Make a PLAIN LLM API call and return the raw response text.

        This is the only method subclasses must implement. It must NOT force
        the cot/out JSON contract — free-form callers (summarizer, nudges)
        depend on plain text here. Structured replies go through _call_api_json.
        """
        pass

    def _call_api_json(self, system_prompt: str, user_message: str) -> str:
        """Structured-output variant used by the cot/out contract.

        Backends with a native JSON-forcing mechanism (e.g. Claude assistant
        prefill) override this. The default delegates to ``_call_api`` and
        relies on the prompt's JSON instruction + the tolerant parser. Keeping
        this separate from ``_call_api`` guarantees plain-text callers are never
        forced into JSON mode.
        """
        return self._call_api(system_prompt, user_message)

    # ── knowledge base ────────────────────────────────────────────────────

    def _load_domain_context(
        self,
        domain: str,
        paths: Optional[Iterable[Path]] = None,
    ) -> str:
        """Load domain-specific knowledge base content.

        When ``paths`` is None, every ``.md`` in the domain directory is
        included (legacy behavior). When provided, only those paths inside
        the domain directory are loaded — used by the KB router to inject
        a per-turn subset.
        """
        domain_dir = self.kb_dir / domain
        if not domain_dir.exists():
            return ""

        if paths is None:
            files: List[Path] = sorted(domain_dir.glob("*.md"))
        else:
            files = [p for p in paths if p.parent == domain_dir and p.exists()]

        context_parts = []
        for md_file in files:
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

    _USE_CASES_DIR = _PROMPTS_DIR / "use_cases"
    _use_case_cache: Dict[str, str] = {}

    @classmethod
    def _load_use_case_block(cls, tag: str) -> str:
        """Read a use-case instruction block from prompts/use_cases/{tag}.md.

        Cached on first read. Returns empty string if the file is missing —
        the router's allowlist already constrains ``tag`` so this is mostly
        a defensive guard against typos during prompt edits.
        """
        if tag in cls._use_case_cache:
            return cls._use_case_cache[tag]
        path = cls._USE_CASES_DIR / f"{tag}.md"
        content = _read_file(path)
        cls._use_case_cache[tag] = content
        return content

    def _build_system_prompt(
        self,
        domain: str,
        user_profile: str = "",
        memory_summary: str = "",
        extracted_facts: str = "",
        transcript: str = "",
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """Build system prompt from versioned template + user context + KB + use-cases.

        When the KB router is enabled and a ``transcript`` is provided, only
        the routed subset of ``helpdesk/*.md`` is injected. The router also
        returns 0+ use-case tags; matching instruction blocks are appended
        after the KB section so the model sees task-specific guidance for
        the current turn.

        ``conversation_history`` (when provided) is forwarded to the LLM
        router so it can disambiguate short follow-up turns from their
        surrounding context. The keyword fallback ignores it.
        """
        version = getattr(self.config, "prompt_version", "current")
        prompt = self._load_prompt_template(version)

        # Inject helpdesk KB + use-case tags via the router. The router always
        # returns _index.md plus 0..N matched docs; use_cases is empty for
        # companion-mode chitchat and for the keyword-fallback path.
        helpdesk_paths: Optional[List[Path]] = None
        use_case_tags: List[str] = []
        if self._kb_router is not None and transcript:
            result = self._kb_router.route(
                transcript,
                top_n=getattr(self.config, "kb_router_top_n", 3),
                threshold=getattr(self.config, "kb_router_threshold", 0.05),
                conversation_history=conversation_history,
            )
            helpdesk_paths = result.paths
            use_case_tags = result.use_cases
        helpdesk_kb = self._load_domain_context("helpdesk", paths=helpdesk_paths)
        if helpdesk_kb:
            prompt += f"\n\n=== Helpdesk Knowledge Base (documents, schemes) ===\n{helpdesk_kb}"

        if use_case_tags:
            blocks = [
                block
                for block in (self._load_use_case_block(tag) for tag in use_case_tags)
                if block
            ]
            if blocks:
                prompt += (
                    "\n\n=== Active Use Cases (apply to THIS turn) ===\n\n"
                    + "\n\n".join(blocks)
                )

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
        "खाना": {
            "वड़ा",
            "पाव",
            "भाजी",
            "खाना",
            "खाती",
            "खाते",
            "ठेला",
            "चाय",
            "चीज़",
            "घी",
            "recipe",
            "बनाता",
            "बनाती",
            "पीती",
            "पीते",
            "सरदार",
            "favourite",
            "dish",
            "food",
            "भूख",
            "नाश्ता",
            "बिरयानी",
        },
        "मुंबई": {
            "लोकल",
            "ट्रेन",
            "भीड़",
            "ऑटो",
            "मीटर",
            "station",
            "स्टेशन",
            "किलोमीटर",
            "ट्रैफ़िक",
            "बारिश",
            "मुंबई",
            "धारावी",
        },
        "काम": {
            "बैग",
            "design",
            "बना",
            "बनाती",
            "order",
            "काम",
            "office",
            "product",
            "pattern",
            "हाथ",
            "machine",
            "शिफ्ट",
        },
        "मौसम": {"गर्मी", "बारिश", "सर्दी", "धूप", "मौसम", "पानी", "भीगना", "ठंड"},
        "Bollywood": {
            "गाना",
            "शाहरुख़",
            "फ़िल्म",
            "actor",
            "actress",
            "Bollywood",
            "गाती",
            "गाते",
        },
        "परिवार": {
            "बेटा",
            "बेटी",
            "school",
            "बच्चे",
            "शरारत",
            "prize",
            "पढ़ाई",
            "बीवी",
            "पति",
            "घर",
            "परिवार",
            "माँ",
            "पापा",
            "भाई",
        },
        "ज़िंदगी": {
            "Sunday",
            "छुट्टी",
            "plan",
            "ख़ुशी",
            "याद",
            "सुबह",
            "superpower",
            "सपना",
            "इंसान",
        },
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
                    f'[सुझाव: "{topic}" पर काफ़ी बात हो चुकी है। '
                    f"अगर user ने छोटा जवाब दिया है तो smoothly topic बदलो — "
                    f'"अच्छा एक बात बताओ —" बोलो और {alt_str} में से कुछ पूछो। '
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

    # Valid ESCALATE_CATEGORY values. Anything else → routed as "grievance"
    # (the default impact-team list). Office-specific docs categories route
    # to the per-office recipients (see escalations/handler.py).
    _ESCALATION_CATEGORIES = ("docs_bc", "docs_midc", "docs_unknown", "grievance")

    @staticmethod
    def _detect_escalation_category(text: str) -> Optional[str]:
        """Detect the office/topic routing category from the LLM response.

        Returns one of: 'docs_bc', 'docs_midc', 'docs_unknown', 'grievance', or
        None if the model didn't emit a category (caller treats None as
        'grievance' default). Unknown category strings also return None so
        a bad model output can't silently misroute.
        """
        match = re.search(
            r"ESCALATE_CATEGORY\s*:\s*([a-zA-Z_]+)", text, flags=re.IGNORECASE
        )
        if not match:
            return None
        value = match.group(1).lower()
        if value in BaseLLM._ESCALATION_CATEGORIES:
            return value
        return None

    @staticmethod
    def _clean_response(raw_text: str, strip_emotions: bool = False) -> str:
        """Remove ESCALATE/EMOTIONS_JSON lines, <memory> blocks, and markdown.

        Markdown leaks (asterisks, bullet markers) get read literally by TTS
        ("asterisk asterisk", "dash"). We strip them as a safety net even
        though the prompt also forbids them.

        <memory> blocks (see ``MEMORY_INSTRUCTION``) are model-internal
        notes the user must never hear. They're stripped before reasoning-
        leak detection so their contents can't accidentally trip outreach
        or jargon filters.

        Also strips chain-of-thought leakage — paragraphs where the model
        narrates its reasoning ("system prompt कहता है...", "anti-sycophancy
        rule apply होता है...") before the actual response. Even though the
        prompt forbids this, the model can still slip when rules conflict.
        """
        # First strip memory patches (must precede reasoning-leak detection
        # so memory contents don't trip the jargon filter), then reasoning
        # leakage at the paragraph level, then per-line cleanup.
        text = BaseLLM._strip_memory_patches(raw_text)
        text = BaseLLM._strip_reasoning_leak(text)

        cleaned_lines = []
        for line in text.splitlines():
            if "ESCALATE" in line.upper():
                continue
            if strip_emotions and line.strip().startswith("EMOTIONS_JSON:"):
                continue
            stripped = line.strip()
            if stripped:
                cleaned_lines.append(stripped)
        text = "\n".join(cleaned_lines).strip()
        return BaseLLM._strip_markdown(text)

    # Matches a single <memory>...</memory> block. DOTALL so multi-line
    # summary patches are captured. Case-insensitive on the tag in case the
    # model slips on capitalisation.
    _MEMORY_BLOCK_RE = re.compile(
        r"<memory>(.*?)</memory>", flags=re.DOTALL | re.IGNORECASE
    )

    @staticmethod
    def _strip_memory_patches(raw_text: str) -> str:
        """Remove all <memory>...</memory> blocks from text.

        Idempotent. Collapses adjacent blank lines left behind so the
        spoken reply doesn't develop awkward gaps.
        """
        if not raw_text or "<memory" not in raw_text.lower():
            return raw_text
        stripped = BaseLLM._MEMORY_BLOCK_RE.sub("", raw_text)
        # Collapse 3+ newlines left from removing blocks back to 2.
        stripped = re.sub(r"\n{3,}", "\n\n", stripped)
        return stripped.strip()

    @staticmethod
    def _parse_memory_patches(raw_text: str) -> Optional[Dict[str, Any]]:
        """Extract memory ops from a raw LLM response.

        Returns ``{"summary": Optional[str], "facts": List[str]}`` if any
        ``<memory>`` block was found, else ``None``. Only the LAST
        ``summary:`` block in the response is kept (later overrides earlier);
        all ``fact:`` blocks are collected in order. Unknown operation
        prefixes are logged and ignored.

        The caller (the webhook) is responsible for actually persisting
        these patches via ``ConversationStore.save_memory()`` — BaseLLM
        stays store-ignorant.
        """
        if not raw_text or "<memory" not in raw_text.lower():
            return None

        facts: List[str] = []
        summary: Optional[str] = None
        for match in BaseLLM._MEMORY_BLOCK_RE.finditer(raw_text):
            body = match.group(1).strip()
            if not body:
                continue
            # Split on the first colon to get the op prefix.
            if ":" not in body:
                import logging

                logging.getLogger("bhai.llm").warning(
                    "Memory block missing op prefix, ignored: %r", body[:60]
                )
                continue
            op_raw, value = body.split(":", 1)
            op = op_raw.strip().lower()
            value = value.strip()
            if not value:
                continue
            if op == "fact":
                facts.append(value)
            elif op == "summary":
                summary = value
            else:
                import logging

                logging.getLogger("bhai.llm").warning(
                    "Unknown memory op %r, ignored", op
                )

        if not facts and summary is None:
            return None
        return {"summary": summary, "facts": facts}

    # Markers that indicate the model is narrating its own reasoning instead
    # of speaking to the user. These terms should NEVER appear in a
    # Hindi/Marathi/Gujarati voice note. If any of them shows up in a
    # paragraph, that paragraph is treated as leaked reasoning and dropped.
    #
    # The "KB" family was added 2026-05-27 after dev test caught bhAI saying
    # "मेरे KB में college scholarship का detail नहीं है" — pure architectural
    # jargon a non-technical user can't parse. The prompt now forbids these
    # explicitly (scheme_kb.md rule 4); these markers are a defense-in-depth
    # backstop when the prompt rule fails. We deliberately use multi-word
    # phrases (not just "KB" alone) to avoid false positives on legitimate
    # use of "KB" as a unit or product name.
    _REASONING_LEAK_MARKERS = (
        "system prompt",
        "anti-sycophancy",
        "TTS engine",
        "the rule",
        "this rule",
        "conflict है",
        "rule apply",
        "मुझे पहले",
        "let me think",
        "मुझे सोच",
        "knowledge base",
        "मेरे KB",
        "मेरी KB",
        "मेरे helpdesk",
        "मेरी helpdesk",
        "helpdesk KB",
        "injected content",
        "context window",
    )

    @staticmethod
    def _strip_reasoning_leak(raw_text: str) -> str:
        """Drop paragraphs that look like the model is narrating its reasoning.

        Splits on blank-line paragraph boundaries. Any paragraph containing
        an internal-jargon marker (see `_REASONING_LEAK_MARKERS`) is dropped.
        If the entire response gets dropped, returns the LAST paragraph as a
        last-ditch fallback (better something than nothing).
        """
        if not raw_text:
            return raw_text

        paragraphs = re.split(r"\n\s*\n", raw_text)
        kept = []
        dropped_any = False
        for para in paragraphs:
            lowered = para.lower()
            if any(m.lower() in lowered for m in BaseLLM._REASONING_LEAK_MARKERS):
                dropped_any = True
                continue
            kept.append(para)

        if dropped_any:
            import logging

            logging.getLogger("bhai.llm").warning(
                "Reasoning leak detected and stripped (paragraphs dropped: %d)",
                len(paragraphs) - len(kept),
            )

        if not kept:
            # Worst case: every paragraph contained reasoning. Keep the last
            # one so the user gets *something* — better than empty silence.
            return paragraphs[-1].strip() if paragraphs else raw_text

        return "\n\n".join(kept).strip()

    # Named human contacts bhAI cannot actually message today. Used by
    # `_detect_outreach_claim` to flag confabulated outreach. "impact team"
    # is included as a phrase; "team" alone is too noisy.
    _OUTREACH_CONTACTS = (
        "Vijay",
        "Priti",
        "Rishi",
        "Sarfaraz",
        "Vidhi",
        "impact team",
    )

    @staticmethod
    def _detect_outreach_claim(text: str, escalate: bool) -> Optional[str]:
        """Detect confabulated outreach claims (past or future tense).

        bhAI cannot actually message Vijay, Priti, Rishi, Sarfaraz, Vidhi,
        or the impact team today. The only legitimate outreach channel is
        consent-gated ``ESCALATE: true`` (which triggers a real email via
        the escalation pipeline).

        Past-tense outreach is always a lie — bhAI cannot have already
        asked anyone synchronously in this turn. Future-tense outreach is
        a lie *unless* ``escalate`` is ``True``, in which case the system
        will actually email the impact team after this response.

        Returns a short description of the violation if found, else
        ``None``. Intentionally narrow (high precision over recall) — a
        false positive that strips an honest reply is worse than missing
        an edge case the next eval iteration can catch.
        """
        if not text:
            return None

        contacts = "(" + "|".join(BaseLLM._OUTREACH_CONTACTS) + ")"

        # Past-tense outreach — always a lie, regardless of ESCALATE.
        past_patterns = [
            # "मैंने X से पूछा / बता दिया" — first-person past with contact nearby
            rf"(मैंने|मैने)\s+\S{{0,30}}?(पूछ|बता|बोल|message कर)",
            # "Vijay ने बताया / कहा / बोला"
            rf"{contacts}\s+(?:Sir\s+|जी\s+)?ने\s+(बताया|कहा|बोला|कह\s+दिया)",
            # "Vijay का जवाब आया / मिला"
            rf"{contacts}\s+(का|की)\s+\S{{0,15}}?(जवाब|reply)\s+(आया|मिला|आ\s+गया)",
            # "Vijay से पूछ लिया" — past completed action near contact
            rf"{contacts}.{{0,40}}?(पूछ\s+लिया|बता\s+दिया|बोल\s+दिया|message\s+कर\s+दिया)",
            rf"(पूछ\s+लिया|बता\s+दिया|बोल\s+दिया|message\s+कर\s+दिया).{{0,40}}?{contacts}",
        ]
        for pat in past_patterns:
            m = re.search(pat, text)
            if m:
                snippet = m.group(0).replace("\n", " ")[:80]
                return f"past-tense outreach: '{snippet}'"

        # Future-tense outreach — lie unless ESCALATE: true (consent-gated).
        if not escalate:
            future_patterns = [
                # "मैं Vijay/team से/को X" (पूछ/बता/message/email/etc.)
                rf"मैं\s+{contacts}(?:\s+|को|से)\s*\S{{0,25}}?"
                rf"(पूछ|बता|बोल|message|email|note|forward|contact)",
                # "Vijay से/को पूछ के बताऊँगी" or similar future commitments
                rf"{contacts}\s+(से|को)\s+\S{{0,30}}?"
                rf"(पूछूँगी|बताऊँगी|बता\s+दूँगी|message\s+करूँगी|email\s+करूँगी|"
                rf"पूछ\s+के\s+बताऊँगी|पूछ\s+के\s+बताती\s+हूँ)",
            ]
            for pat in future_patterns:
                m = re.search(pat, text)
                if not m:
                    continue
                # Negation suppression: if "नहीं" appears in a small window
                # around the match, this is an honest disclaimer, not a lie.
                # e.g. "मैं Vijay को directly message नहीं कर सकती"
                window = text[max(0, m.start() - 20) : m.end() + 20]
                if "नहीं" in window:
                    continue
                snippet = m.group(0).replace("\n", " ")[:80]
                return f"future-tense outreach (no ESCALATE): '{snippet}'"

        return None

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """Strip markdown so TTS doesn't read it literally.

        Devanagari Hindi text never contains asterisks/backticks, so we
        can safely scrub them. Leading bullet/numbered list markers and
        markdown headings are also stripped.

        Note: phone-number stripping is NOT done here. That's handled
        independently by ``inference/webhooks/telegram_webhook._extract_phone_numbers``,
        which both strips the digits from the voice text AND assembles a
        labelled Telegram text message ("📞 Contact: Priti (BC) – ...") for
        the user. Keeping the two in sync is intentional: the webhook owns
        the contact-number text-message channel end-to-end.
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

    # Unicode blocks that are mostly emoji / symbol pictographs. Stripping
    # these prevents Sarvam TTS from reading them as their literal Unicode
    # names ("face with tears of joy"). Devanagari and other Indic scripts
    # live in lower code points (U+0900-U+0DFF, U+0B80-U+0BFF, etc.) and
    # are NOT in this pattern.
    _EMOJI_PATTERN = re.compile(
        "["
        "\U0001f300-\U0001f5ff"  # symbols & pictographs
        "\U0001f600-\U0001f64f"  # emoticons
        "\U0001f680-\U0001f6ff"  # transport & map
        "\U0001f700-\U0001f77f"  # alchemical
        "\U0001f780-\U0001f7ff"  # geometric shapes ext.
        "\U0001f800-\U0001f8ff"  # supplemental arrows-c
        "\U0001f900-\U0001f9ff"  # supplemental symbols & pictographs
        "\U0001fa00-\U0001fa6f"  # chess
        "\U0001fa70-\U0001faff"  # symbols & pictographs ext-a
        "\U00002600-\U000026ff"  # misc symbols (☀ ☔ ⚽ etc.)
        "\U00002700-\U000027bf"  # dingbats (✂ ✔ ✨ etc.)
        "\U0000fe00-\U0000fe0f"  # variation selectors
        "\U0000200d"  # ZWJ
        "]+",
        flags=re.UNICODE,
    )

    @staticmethod
    def _strip_emoji(text: str) -> str:
        """Remove Unicode emoji codepoints.

        Sarvam TTS reads emojis as their Unicode names ("face with tears
        of joy") — unusable in a voice note. We strip them here so the
        structured-output `out` text never carries them to TTS or to the
        Telegram message body. Indic scripts are NOT affected (they live
        below U+0E00 and outside every range in _EMOJI_PATTERN).
        """
        if not text:
            return text
        cleaned = BaseLLM._EMOJI_PATTERN.sub("", text)
        # Mid-sentence emoji removal leaves "word  word" — collapse the gap.
        cleaned = re.sub(r" {2,}", " ", cleaned)
        return cleaned.strip()

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

    # ── structured output parsing (cot / out contract) ───────────────────

    @staticmethod
    def _json_unescape(s: str) -> str:
        """Unescape a JSON string body (the text between the quotes)."""
        try:
            return str(json.loads(f'"{s}"'))
        except (json.JSONDecodeError, ValueError):
            return s

    @staticmethod
    def _parse_structured_output(raw_text: str) -> Tuple[str, str, bool]:
        """Parse the {"cot", "out", "escalate"} JSON contract from raw output.

        Tolerant by design: handles code fences, leading/trailing prose around
        the object, and a final regex that pulls just the "out" value when the
        JSON is malformed. Returns ``(cot, out, escalate)``; ``out`` is "" when
        nothing usable could be extracted, signalling the caller to use a safe
        fallback rather than ever delivering raw text.
        """
        if not raw_text:
            return "", "", False

        s = raw_text.strip()

        # Strip ```json ... ``` fences if the model wrapped the object.
        if s.startswith("```"):
            s = re.sub(r"^```[a-zA-Z0-9]*\n?", "", s)
            s = re.sub(r"\n?```\s*$", "", s).strip()

        # Try the whole string, then the {...} substring (drops surrounding prose).
        candidates = [s]
        first, last = s.find("{"), s.rfind("}")
        if first != -1 and last != -1 and last > first:
            candidates.append(s[first : last + 1])

        for cand in candidates:
            try:
                obj = json.loads(cand)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(obj, dict) and isinstance(obj.get("out"), str):
                cot = obj.get("cot")
                return (
                    cot if isinstance(cot, str) else "",
                    obj["out"],
                    bool(obj.get("escalate", False)),
                )

        # Last resort: regex-extract the "out" (and "cot"/"escalate") values.
        out_m = re.search(r'"out"\s*:\s*"((?:[^"\\]|\\.)*)"', s)
        if out_m:
            cot_m = re.search(r'"cot"\s*:\s*"((?:[^"\\]|\\.)*)"', s)
            esc_m = re.search(r'"escalate"\s*:\s*(true|false)', s, re.IGNORECASE)
            return (
                BaseLLM._json_unescape(cot_m.group(1)) if cot_m else "",
                BaseLLM._json_unescape(out_m.group(1)),
                bool(esc_m and esc_m.group(1).lower() == "true"),
            )

        return "", "", False

    def _generate_structured(
        self, system_prompt: str, user_message: str
    ) -> Dict[str, Any]:
        """Call the model, parse the cot/out/escalate JSON, return cleaned out.

        On a cot/out parse failure the whole call is re-rolled up to
        ``config.llm_json_max_attempts`` times (each re-roll is a fresh
        generation, so non-zero temperature usually yields valid JSON next
        time). Only after every attempt fails do we drop to a safe canned line
        — never to raw text. ``out`` is run through markdown stripping as a TTS
        safety net.
        """
        max_attempts = max(1, int(getattr(self.config, "llm_json_max_attempts", 3)))

        raw, cot, out, escalate = "", "", "", False
        for attempt in range(1, max_attempts + 1):
            raw = self._call_api_json_with_retry(system_prompt, user_message)
            cot, out, escalate = self._parse_structured_output(raw)
            if out:
                break
            logger.warning(
                "cot/out parse failed (attempt %d/%d); retrying. raw=%r",
                attempt,
                max_attempts,
                raw[:300],
            )

        parsed = bool(out)
        if not parsed:
            logger.error(
                "cot/out parse failed after %d attempts; using fallback.",
                max_attempts,
            )
            out = _FALLBACK_OUT
            escalate = False  # never escalate off a failed/fallback response

        if cot:
            logger.info("cot: %s", cot[:300])

        # Stripping order (each runs on the output of the previous):
        #   1. memory patches  — <memory>...</memory> blocks live INSIDE `out`
        #      per MEMORY_INSTRUCTION; the patches are extracted upstream from
        #      `raw`, here we strip them from the spoken text.
        #   2. escalate-category line  — "ESCALATE_CATEGORY: docs_bc" is also
        #      inside `out` and gets read aloud by TTS if left in.
        #   3. markdown  — asterisks/headers/list markers from the model.
        #   4. emoji  — Sarvam TTS reads emojis as their Unicode names.
        cleaned = self._strip_memory_patches(out)
        cleaned = "\n".join(
            line
            for line in cleaned.splitlines()
            if not line.strip().upper().startswith("ESCALATE_CATEGORY")
            and not line.strip().upper().startswith("ESCALATE:")
        )
        text = self._strip_emoji(self._strip_markdown(cleaned)).strip()
        if not text:
            # Parsed but empty after markdown stripping — treat as a failure too.
            text = _FALLBACK_OUT
            parsed = False
            escalate = False

        # ``parsed`` lets callers distinguish a real reply from the safe canned
        # fallback (e.g. nudges skip sending rather than speak the fallback).
        return {
            "text": text,
            "raw": raw,
            "cot": cot,
            "parsed": parsed,
            "escalate": escalate,
        }

    # ── retry helper ─────────────────────────────────────────────────────

    _OUTREACH_CORRECTION_PROMPT = (
        "\n\nIMPORTANT correction for your next reply: your previous draft "
        "contained a confabulated outreach claim — you implied you would "
        "(or did) message someone like Vijay, Priti, Rishi, Sarfaraz, "
        "Vidhi, or the impact team. You CANNOT actually message anyone "
        "today outside the consent-gated ESCALATE: true flow. Rewrite the "
        "response: name the capability limit honestly ('मैं अभी directly "
        "किसी को message नहीं कर सकती'), and route the user to a direct "
        "contact number (text the number for documents/schemes from the "
        "KB) or just answer the underlying question yourself without "
        "claiming any outreach. Do not output the same draft."
    )

    def _guard_outreach(
        self,
        result: Dict[str, Any],
        system_prompt: str,
        user_message: str,
    ) -> Dict[str, Any]:
        """One-shot re-prompt if a confabulated outreach claim is detected.

        Operates on the cot/out structured ``result``. bhAI cannot message
        anyone today outside the consent-gated ``escalate`` flow. If ``out``
        contains a past-tense or (non-escalate) future-tense outreach claim
        against a named contact, log the violation, re-prompt once with a
        corrective system message, and return the corrected structured result.
        If the second draft still fails, emit a warning but return it —
        silence is worse than a logged warning.
        """
        violation = BaseLLM._detect_outreach_claim(
            result["text"], result.get("escalate", False)
        )
        if not violation:
            return result

        logger.warning("Confabulated outreach detected, re-prompting: %s", violation)

        corrected_prompt = system_prompt + self._OUTREACH_CORRECTION_PROMPT
        try:
            new_result = self._generate_structured(corrected_prompt, user_message)
        except Exception:  # pragma: no cover - defensive fallback
            logger.exception("Outreach re-prompt failed; keeping original draft")
            return result

        residual = BaseLLM._detect_outreach_claim(
            new_result["text"], new_result.get("escalate", False)
        )
        if residual:
            logger.warning(
                "Outreach claim persisted after re-prompt: %s (emitting anyway)",
                residual,
            )

        return new_result

    def _call_api_with_retry(
        self, system_prompt: str, user_message: str, max_attempts: int = 3
    ) -> str:
        """Call _call_api (plain) with retry and exponential backoff."""
        return retry_with_backoff(
            self._call_api,
            system_prompt,
            user_message,
            max_attempts=max_attempts,
            base_delay=1.0,
            max_delay=10.0,
        )

    def _call_api_json_with_retry(
        self, system_prompt: str, user_message: str, max_attempts: int = 3
    ) -> str:
        """Call _call_api_json (structured cot/out) with retry and backoff."""
        return retry_with_backoff(
            self._call_api_json,
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
            Dictionary with text (the parsed "out"), raw, cot, and escalate.
        """
        system_prompt = (
            self._build_system_prompt(
                domain,
                user_profile,
                memory_summary,
                extracted_facts,
                transcript,
                conversation_history=conversation_history,
            )
            + MEMORY_INSTRUCTION
            + _JSON_OUTPUT_INSTRUCTION
        )
        user_message = self._build_user_message(
            transcript, conversation_history, is_new_session
        )
        result = self._generate_structured(system_prompt, user_message)
        # One-shot re-prompt if the reply confabulates outreach (bhAI can only
        # message anyone via the consent-gated escalate flow).
        result = self._guard_outreach(result, system_prompt, user_message)

        # Memory patches parsed from the FINAL raw output (after any outreach
        # re-prompt). The webhook applies them via store.save_memory().
        memory_patches = self._parse_memory_patches(result["raw"])

        return {
            "text": result["text"],
            "raw": result["raw"],
            "cot": result["cot"],
            "parsed": result["parsed"],
            "escalate": result["escalate"],
            "category": self._detect_escalation_category(result["raw"]),
            "memory_patches": memory_patches,
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

        Returns dict with text (the parsed "out"), raw, cot, escalate, and a
        single neutral segment (per-segment emotions were dropped in favour of
        the cot/out JSON contract; the Telegram TTS path re-chunks plain text).
        """
        system_prompt = (
            self._build_system_prompt(
                domain,
                user_profile,
                memory_summary,
                extracted_facts,
                transcript,
                conversation_history=conversation_history,
            )
            + MEMORY_INSTRUCTION
        )
        # EMOTION_INSTRUCTION intentionally NOT appended — per-segment
        # emotions were dropped (see docstring above), and on the new
        # `output_config.format` path the trailing "EMOTIONS_JSON: [...]"
        # line slips into the `out` string and gets read aloud by TTS.
        if mode_instruction:
            system_prompt += "\n\n" + mode_instruction
        system_prompt += _JSON_OUTPUT_INSTRUCTION

        user_message = self._build_user_message(
            transcript, conversation_history, is_new_session
        )
        result = self._generate_structured(system_prompt, user_message)
        result = self._guard_outreach(result, system_prompt, user_message)
        text = result["text"]

        memory_patches = self._parse_memory_patches(result["raw"])

        return {
            "text": text,
            "raw": result["raw"],
            "cot": result["cot"],
            "parsed": result["parsed"],
            "escalate": result["escalate"],
            "segments": [{"text": text, "emotion": "neutral"}],
            "category": self._detect_escalation_category(result["raw"]),
            "memory_patches": memory_patches,
        }
