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
``BaseLLM._parse_thread_patches`` extracts them into ``ThreadPatch``
objects (piece A). This module also owns the storage shape (``Thread``
dataclass + state allowlist) consumed by the persistence layer in
``ConversationStore`` (piece B).

Operations:

    open: <slug> / <context>          create a new dormant thread (ready to nudge)
    update: <slug> / <context>        append context to an existing thread
    close: <slug> / <reason>          mark closed — won't be nudged again
    mark_sensitive: <slug>            tag do_not_nudge until user re-raises

States:

    dormant         open + eligible for the next proactive nudge
    active          just nudged; watching the user's reaction
    closed          resolved — no further nudging
    do_not_nudge    sensitive; surfaced for situational awareness only

Slug format: lowercase letters, digits, underscores. The slug is the
stable key the dossier and the thinker key off; it should describe the
THREAD ("saree_business_expansion") not the FACT
("manimalas_2026_05_loan_amount"). Each thread is one durable concern
followed across many turns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Valid op prefixes the LLM may emit. Anything else is logged and ignored
# at parse time — strict allowlisting avoids silent drift into ad-hoc
# operations the persistence layer doesn't know how to apply.
THREAD_OPS = ("open", "update", "close", "mark_sensitive")

# Persisted thread states. `dormant` is the initial state after `open`
# (or after auto-promotion from `update` on a missing slug). The
# proactive thinker transitions `dormant → active` when it fires a nudge
# referencing the thread (via ``ConversationStore.mark_thread_nudged``),
# so the next thinking pass can tell which threads it's already poked.
# `closed` and `do_not_nudge` are sticky — only an `open` op (which
# reopens a closed slug) can move out of them.
THREAD_STATES = ("dormant", "active", "closed", "do_not_nudge")

# Slugs are kebab/snake-style identifiers; we accept lowercase letters,
# digits, and underscores. Hyphens are intentionally excluded so the slug
# survives round-tripping through any format that treats hyphens
# specially (Markdown, URL paths). Length 1-80 chars.
SLUG_PATTERN = re.compile(r"^[a-z0-9_]{1,80}$")

# Hard cap on per-thread history rows kept inside the encrypted history
# blob. Bounds row size so a chatty thread can't pathologically inflate
# the SQLite database; oldest entries fall off first.
MAX_HISTORY_ENTRIES = 20


@dataclass
class ThreadPatch:
    """One self-edited thread operation parsed from an LLM response.

    The reactive turn emits zero or more of these inside ``<thread>...
    </thread>`` blocks. The webhook is responsible for applying them
    via ``ConversationStore.apply_thread_patches()``;
    ``BaseLLM`` stays storage-ignorant the same way it stays
    storage-ignorant about memory patches.
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


@dataclass
class Thread:
    """One persisted open thread, as returned by
    ``ConversationStore.list_threads`` / ``get_thread``.

    ``context`` is the latest one-line summary (the most recent ``open``
    or ``update`` body, or the ``close`` reason). ``history`` is the
    append-only log of past ops, capped at ``MAX_HISTORY_ENTRIES``;
    each entry is ``{"ts": iso, "op": <op>, "context": str}``.
    """

    phone: str
    slug: str
    state: str  # one of THREAD_STATES
    context: str
    history: List[Dict[str, str]] = field(default_factory=list)
    opened_at: str = ""
    last_touched_at: str = ""
    last_nudged_at: Optional[str] = None
