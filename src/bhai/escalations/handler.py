"""
Escalation handler — fires when the LLM emits ESCALATE: true.

Flow (trust-restoring two-message pattern):
1. The LLM's promise voice note ("Main team ko email karne wali hoon...") has
   already been sent to the user by the time we're called.
2. We send the escalation email to the right recipients for the category
   (see _recipients_for_category below).
3. One retry after RETRY_DELAY_SECONDS on first failure.
4. We synthesize and send a follow-up voice note confirming success
   ("Email kar diya...") or honest failure ("Abhi email nahi ja paaya...").
5. The confirmation message is persisted to the conversation store so the
   next-turn LLM context knows it happened.

Voice synthesis is injected as a callable so this module doesn't depend on
telegram_webhook.py (which would create an import cycle).
"""

import asyncio
import html
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from ..config import Config
from ..integrations.email_client import EmailClient
from ..memory.store import ConversationStore

logger = logging.getLogger("bhai.escalations.handler")

IST = timezone(timedelta(hours=5, minutes=30))

CONFIRM_SUCCESS_HI = "Email kar diya. Woh aapko call karenge."
CONFIRM_FAILURE_HI = (
    "Abhi email nahi ja paaya, main thodi der mein dobara koshish karungi."
)
RETRY_DELAY_SECONDS = 30

# Matches `work_location: BC` / `work_location: MIDC` (case-insensitive,
# tolerant of spacing) anywhere in a fact string or profile text.
_WORK_LOCATION_RE = re.compile(
    r"work[_ ]?location\s*[:=]\s*(BC|MIDC)\b", flags=re.IGNORECASE
)

# Valid ESCALATE_CATEGORY values the LLM may emit. Anything else (or absent)
# → routed as "mental_health" (the default impact-team list — the safe
# fallback, since an unclassified escalation may be a welfare/safety case).
_VALID_CATEGORIES = (
    "docs_bc",
    "docs_midc",
    "docs_unknown",
    "workplace",
    "mental_health",
)
_CATEGORY_RE = re.compile(r"ESCALATE_CATEGORY\s*:\s*([a-zA-Z_]+)", re.IGNORECASE)


def parse_escalation_category(raw_text: str) -> Optional[str]:
    """Parse `ESCALATE_CATEGORY: <value>` from the LLM's raw response.

    Returns one of `_VALID_CATEGORIES` or None if missing / unknown. None
    is treated by the handler as 'grievance' default — so unknown category
    strings can't silently misroute, they fall back to the safe path.
    """
    if not raw_text:
        return None
    match = _CATEGORY_RE.search(raw_text)
    if not match:
        return None
    value = match.group(1).lower()
    if value in _VALID_CATEGORIES:
        return value
    return None


def _extract_work_location(
    store: ConversationStore, phone: str, user_profile: str
) -> Optional[str]:
    """Pull `BC` or `MIDC` from the user's facts or profile, if known.

    The prompt's MEMORY_INSTRUCTION asks the model to emit
    ``<memory>fact: work_location: BC</memory>`` (or MIDC) as soon as the
    user mentions her office, and the webhook persists those into facts.
    Profiles may also carry the location in free text.

    Returns the uppercase string ``"BC"`` / ``"MIDC"`` or ``None`` if not
    found in either source.
    """
    try:
        memory = store.get_memory(phone)
    except Exception as e:
        logger.warning(
            "Could not load memory for work_location lookup user=%s: %s",
            phone[:8],
            e,
        )
        memory = None

    if memory:
        for fact in memory.get("facts") or []:
            m = _WORK_LOCATION_RE.search(str(fact))
            if m:
                return m.group(1).upper()

    if user_profile:
        m = _WORK_LOCATION_RE.search(user_profile)
        if m:
            return m.group(1).upper()

    return None


# Voice sender signature: kwargs-only, matches telegram_webhook._synthesize_and_send_voice
VoiceSender = Callable[..., bool]


def _recipients_for_category(
    config: Config, category: Optional[str]
) -> Tuple[List[str], List[str], str]:
    """Pick TO recipients, CC recipients, and a human-readable label for the
    LLM category. Unknown / missing → mental_health (impact-team default).

    CC rule (matches the routing matrix):
      - The OPERATOR (escalation_cc, Sundar) CCs EVERY email — deliverability.
      - The IMPACT HEAD (escalation_impact_head, Anu) CCs every category in
        the impact team's domain — docs_* and mental_health — but NOT
        workplace (HR/Simran is outside the impact team).
    CC is deduped and never repeats a TO address.

    Returns (to_recipients, cc_recipients, label_for_subject).
    """
    operator_cc = list(config.escalation_cc)
    impact_head = list(config.escalation_impact_head)

    def _cc(*, include_impact_head: bool, to: List[str]) -> List[str]:
        raw = (impact_head if include_impact_head else []) + operator_cc
        out: List[str] = []
        for addr in raw:
            if addr and addr not in to and addr not in out:
                out.append(addr)
        return out

    if category == "docs_bc" and config.escalation_recipients_docs_bc:
        to = list(config.escalation_recipients_docs_bc)
        return to, _cc(include_impact_head=True, to=to), "docs_bc"
    if category == "docs_midc" and config.escalation_recipients_docs_midc:
        to = list(config.escalation_recipients_docs_midc)
        return to, _cc(include_impact_head=True, to=to), "docs_midc"
    if category == "docs_unknown" and impact_head:
        # Office still ambiguous after the bot asked → route to the impact
        # head (Anu) to triage to Priti/Dinesh. We do NOT email both offices.
        return (
            list(impact_head),
            _cc(include_impact_head=False, to=list(impact_head)),
            "docs_unknown",
        )
    if category == "workplace" and config.escalation_recipients_workplace:
        to = list(config.escalation_recipients_workplace)
        # HR is outside the impact team — operator CC only, no impact head.
        return to, _cc(include_impact_head=False, to=to), "workplace"
    # Default: mental_health / unknown category → Rishi (TO), Anu + operator
    # (CC). The safe fallback — an unclassified escalation may be a welfare or
    # safety case, so it goes to the team with welfare oversight.
    to = list(config.escalation_recipients)
    return to, _cc(include_impact_head=True, to=to), "mental_health"


async def handle_escalation(
    *,
    config: Config,
    email_client: EmailClient,
    store: ConversationStore,
    voice_sender: VoiceSender,
    phone: str,
    chat_id: int,
    phone_id: str,
    session_id: str,
    user_transcript: str,
    bot_response: str,
    recent_messages: List[dict],
    user_profile: str,
    run_id: str,
    run_dir: Path,
    telegram_client,
    category: Optional[str] = None,
) -> None:
    """Send escalation email, then confirm to user with a voice note.

    Never raises — all failure paths are logged. Designed to be scheduled via
    asyncio.create_task from the webhook handler.

    `category` (from BaseLLM._detect_escalation_category) routes to the right
    recipients: 'docs_bc'→Priti, 'docs_midc'→Dinesh, 'docs_unknown'→Anu
    (triages), 'workplace'→Simran (HR), 'mental_health' / None → Rishi. CC is
    category-aware: the operator (Sundar) CCs every email; the impact head
    (Anu) CCs every category except workplace. See _recipients_for_category.
    """
    if not config.escalation_enabled:
        logger.warning("Escalation skipped for user=%s: escalation disabled", phone_id)
        return

    recipients, cc_list, category_label = _recipients_for_category(config, category)
    if not recipients:
        logger.warning(
            "Escalation skipped for user=%s: no recipients configured for category=%s",
            phone_id,
            category_label,
        )
        return

    # Work location is required per escalation_policy.md. The prompt should
    # ask the user before emitting ESCALATE: true if it's missing; logging
    # loudly here surfaces the cases where it slips through (acute self-harm
    # exception, or model error).
    work_location = _extract_work_location(store, phone, user_profile)
    if not work_location:
        logger.warning(
            "Escalation firing for user=%s WITHOUT known work_location — "
            "impact team will need to ask manually. category=%s",
            phone_id,
            category_label,
        )

    user_hash = hash(phone) % 10000
    timestamp = datetime.now(IST)
    location_tag = work_location or "LOC?"
    subject = (
        f"[bhAI escalation:{category_label}/{location_tag}] user #{user_hash} "
        f"— {timestamp:%Y-%m-%d %H:%M IST}"
    )
    body = _render_html_body(
        phone=phone,
        chat_id=chat_id,
        timestamp=timestamp,
        user_transcript=user_transcript,
        bot_response=bot_response,
        recent_messages=recent_messages,
        user_profile=user_profile,
        category_label=category_label,
        work_location=work_location,
    )

    # cc_list is category-aware (operator always; impact head on impact-team
    # categories) — see _recipients_for_category.
    logger.info(
        "Escalation routing user=%s category=%s recipients=%d cc=%d",
        phone_id,
        category_label,
        len(recipients),
        len(cc_list),
    )

    sent = await email_client.send(
        to=recipients, subject=subject, html_body=body, cc=cc_list
    )
    if not sent:
        logger.warning(
            "Escalation email attempt 1 failed for user=%s, retrying in %ds",
            phone_id,
            RETRY_DELAY_SECONDS,
        )
        await asyncio.sleep(RETRY_DELAY_SECONDS)
        sent = await email_client.send(
            to=recipients, subject=subject, html_body=body, cc=cc_list
        )

    confirm_text = CONFIRM_SUCCESS_HI if sent else CONFIRM_FAILURE_HI
    logger.info("Escalation final outcome user=%s sent=%s", phone_id, sent)

    # Persist the confirm message before the user hears it, so if voice
    # synthesis fails we still have a record that we tried.
    try:
        store.save_message(phone, "assistant", confirm_text, session_id)
    except Exception as e:
        logger.error(
            "Persisting escalation confirm message failed for user=%s: %s",
            phone_id,
            e,
        )

    try:
        voice_sender(
            telegram_client=telegram_client,
            chat_id=chat_id,
            text=confirm_text,
            config=config,
            run_id=f"{run_id}_escalation_confirm",
            run_dir=run_dir,
            phone_id=phone_id,
        )
    except Exception as e:
        logger.error(
            "Escalation confirm voice send failed for user=%s: %s",
            phone_id,
            e,
        )


def _render_html_body(
    *,
    phone: str,
    chat_id: int,
    timestamp: datetime,
    user_transcript: str,
    bot_response: str,
    recent_messages: List[dict],
    user_profile: str,
    category_label: str = "grievance",
    work_location: Optional[str] = None,
) -> str:
    """Render the escalation email body as HTML.

    Phone number is included in full — these recipients are internal Tiny
    Miracles emails and the team needs the number to call the user back.
    """
    parts: List[str] = []
    parts.append("<h2>bhAI escalation triggered</h2>")
    parts.append("<p><b>Category:</b> " + html.escape(category_label) + "</p>")
    if work_location:
        parts.append(
            "<p><b>Work location:</b> " + html.escape(work_location) + " office</p>"
        )
    else:
        parts.append(
            "<p><b>Work location:</b> <i>UNKNOWN — please ask the user when "
            "you follow up</i></p>"
        )
    parts.append("<p><b>User phone:</b> " + html.escape(phone) + "</p>")
    parts.append(f"<p><b>Telegram chat ID:</b> {chat_id}</p>")
    parts.append(f"<p><b>Time (IST):</b> {timestamp:%Y-%m-%d %H:%M:%S}</p>")

    parts.append("<h3>Triggering turn</h3>")
    parts.append("<p><b>User:</b> " + html.escape(user_transcript or "") + "</p>")
    parts.append("<p><b>bhAI:</b> " + html.escape(bot_response or "") + "</p>")

    if recent_messages:
        parts.append("<h3>Recent conversation</h3>")
        parts.append("<ul style='font-family: monospace;'>")
        for msg in recent_messages:
            role = html.escape(str(msg.get("role", "?")))
            content = html.escape(str(msg.get("content", "")))
            ts = html.escape(str(msg.get("timestamp", "")))
            parts.append(f"<li><b>{role}</b> ({ts}): {content}</li>")
        parts.append("</ul>")

    if user_profile and user_profile.strip():
        parts.append("<h3>User profile</h3>")
        parts.append("<pre>" + html.escape(user_profile) + "</pre>")

    return "\n".join(parts)
