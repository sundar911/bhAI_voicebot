"""Assemble the full per-user input the proactive thinking agent sees.

Step 2 of the v2 proactive build (see tmp/v2_proactive_design.md §12). The
dossier loader (step 1) gives us the structured *persistent* state — the
markdown files. The thinking agent also needs the *recent* state — the last
N conversation turns — and a placeholder for the (initially empty)
nudge history it will consult to avoid relentlessness.

`AgentInput` is the single object the agent's brainstorm / critique / draft
prompts will receive. Its `.as_system_prompt_context()` renders the
dossier files as one big context block; its `.as_user_message_context()`
renders the recent conversation for the user-message slot. Splitting the
two means the prompt is built in the standard system/user shape the rest
of the v1.5 LLM stack already uses (see src/bhai/llm/base.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from ..memory.store import ConversationStore
from .dossier_loader import UserDossier, load_user_dossier


@dataclass
class AgentInput:
    """Everything the proactive thinking agent needs about one user.

    Owns the dossier (persistent state — facts, narrative, history files)
    AND the recent conversation (last N turns) so the agent prompt can be
    built from one self-contained object.
    """

    dossier: UserDossier
    recent_messages: List[Dict[str, str]] = field(default_factory=list)

    @property
    def phone(self) -> str:
        return self.dossier.phone

    @property
    def phone_hash(self) -> str:
        return self.dossier.phone_hash

    def as_system_prompt_context(self) -> str:
        """Render the dossier files as the persistent-state block of the
        agent's system prompt. Concatenates every file from the dossier's
        `markdown_map()` separated by horizontal rules so the agent sees
        each domain as its own section.
        """
        files = self.dossier.markdown_map()
        # Stable order so prompt-caching can hit on repeat calls — core /
        # narrative first (always-loaded identity layer), then domain files,
        # then history files at the bottom.
        order = [
            "core.md",
            "narrative.md",
            "family_context.md",
            "financial_threads.md",
            "grievance_log.md",
            "scheme_status.md",
            "outreach_history.md",
            "nudge_history.md",
            "open_threads.md",
        ]
        parts = [f"### {name}\n\n{files[name]}" for name in order if name in files]
        return "\n\n---\n\n".join(parts)

    def as_user_message_context(self) -> str:
        """Render the recent conversation as the user-message context block.

        Matches the v1.5 reactive-path convention (role-tagged lines,
        chronological order) so the agent prompt feels consistent with the
        rest of the stack.
        """
        if not self.recent_messages:
            return "=== Recent Conversation ===\n\n(no recent conversation)\n"

        lines = ["=== Recent Conversation ==="]
        for msg in self.recent_messages:
            role_label = "User" if msg["role"] == "user" else "bhAI"
            ts = msg.get("timestamp", "")
            ts_suffix = f" [{ts}]" if ts else ""
            lines.append(f"\n{role_label}{ts_suffix}: {msg['content']}")
        lines.append("\n=== End Recent Conversation ===")
        return "\n".join(lines)


def build_agent_input(
    store: ConversationStore,
    phone: str,
    *,
    recent_turns: int = 20,
) -> AgentInput:
    """Load the user's dossier + recent conversation in one call.

    `recent_turns` defaults to 20 (10 user + 10 assistant exchanges,
    approximately) — enough to give the agent the current shape of the
    relationship without exceeding the design doc's ~5K-token recent-context
    budget. The reactive path uses 8 turns; we use more because the
    proactive thinking pass is off the latency path and the agent benefits
    from more context to brainstorm against.
    """
    dossier = load_user_dossier(store, phone)
    recent = store.get_recent_messages(phone, limit=recent_turns)
    return AgentInput(dossier=dossier, recent_messages=recent)
