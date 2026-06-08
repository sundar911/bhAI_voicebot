"""Open threads — durable curiosities bhAI is following across days.

Threads are the persistent layer between the reactive surface (one-turn
voice replies) and the proactive surface (the daily thinking pass).
Memory captures FACTS the user disclosed; threads capture CURIOSITIES
the agent has chosen to track across sessions:

- *"Manimala mentioned planning a ₹1L loan for a new Surat supplier"*
  is a thread the agent should follow up on next time her business comes
  up, then close once she's either acted on it or visibly moved on.
- *"Sapna's son's karate / painting classes"* is a thread the agent
  should keep alive — but with `do_not_nudge` while the prior
  Vijay-karate confabulation memory is still fresh, so the proactive
  surface doesn't blunder back into it.

The reactive LLM emits ``<thread>`` blocks alongside ``<memory>`` blocks.
This module defines the patch shape — parsing lives in
``BaseLLM._parse_thread_patches`` (piece A of the open-threads build,
mirrored on the existing memory parser). Persistence and dossier
rendering land in subsequent pieces.

Operations:

    open: <slug> / <context>          create a new active thread
    update: <slug> / <context>        append context to an existing thread
    close: <slug> / <reason>          mark closed — won't be nudged again
    mark_sensitive: <slug>            tag do_not_nudge until user re-raises

Slug format: lowercase letters, digits, underscores. The slug is the
stable key the dossier and the thinker key off; it should describe the
THREAD ("saree_business_expansion") not the FACT
("manimalas_2026_05_loan_amount"). Each thread is one durable concern
followed across many turns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Valid op prefixes the LLM may emit. Anything else is logged and ignored
# at parse time — strict allowlisting avoids silent drift into ad-hoc
# operations the persistence layer doesn't know how to apply.
THREAD_OPS = ("open", "update", "close", "mark_sensitive")

# Slugs are kebab/snake-style identifiers; we accept lowercase letters,
# digits, and underscores. Hyphens are intentionally excluded so the slug
# survives round-tripping through any format that treats hyphens
# specially (Markdown, URL paths). Length 1-80 chars.
SLUG_PATTERN = re.compile(r"^[a-z0-9_]{1,80}$")


@dataclass
class ThreadPatch:
    """One self-edited thread operation parsed from an LLM response.

    The reactive turn emits zero or more of these inside ``<thread>...
    </thread>`` blocks. The webhook is responsible for applying them
    via the (forthcoming) ``apply_thread_patches()`` once the storage
    layer lands; ``BaseLLM`` stays storage-ignorant the same way it
    stays storage-ignorant about memory patches.
    """

    op: str  # one of THREAD_OPS
    topic: str  # slug, validated against SLUG_PATTERN
    context: str = (
        ""  # description (open/update) or reason (close); empty for mark_sensitive
    )

    def is_valid(self) -> bool:
        """A patch is well-formed when its op is in the allowlist, its
        topic matches the slug pattern, and (for open/update/close) a
        non-empty context is provided. ``mark_sensitive`` is the one op
        that doesn't carry a body."""
        if self.op not in THREAD_OPS:
            return False
        if not SLUG_PATTERN.match(self.topic):
            return False
        if self.op == "mark_sensitive":
            return True  # context optional
        return bool(self.context)
