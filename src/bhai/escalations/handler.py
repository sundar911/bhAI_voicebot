"""
Escalation handler — fires when the LLM emits ESCALATE: true.

Flow (trust-restoring two-message pattern):
1. The LLM's promise voice note ("Main team ko email karne wali hoon...") has
   already been sent to the user by the time we're called.
2. We send the escalation email to the impact team (Rishi + Anu by default).
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable, List, Optional

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


# Voice sender signature: kwargs-only, matches telegram_webhook._synthesize_and_send_voice
VoiceSender = Callable[..., bool]


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
) -> None:
    """Send escalation email, then confirm to user with a voice note.

    Never raises — all failure paths are logged. Designed to be scheduled via
    asyncio.create_task from the webhook handler.
    """
    if not config.escalation_enabled or not config.escalation_recipients:
        logger.warning(
            "Escalation skipped for user=%s: enabled=%s, recipients=%d",
            phone_id,
            config.escalation_enabled,
            len(config.escalation_recipients),
        )
        return

    user_hash = hash(phone) % 10000
    timestamp = datetime.now(IST)
    subject = f"[bhAI escalation] user #{user_hash} — {timestamp:%Y-%m-%d %H:%M IST}"
    body = _render_html_body(
        phone=phone,
        chat_id=chat_id,
        timestamp=timestamp,
        user_transcript=user_transcript,
        bot_response=bot_response,
        recent_messages=recent_messages,
        user_profile=user_profile,
    )
    recipients = list(config.escalation_recipients)

    sent = await email_client.send(to=recipients, subject=subject, html_body=body)
    if not sent:
        logger.warning(
            "Escalation email attempt 1 failed for user=%s, retrying in %ds",
            phone_id,
            RETRY_DELAY_SECONDS,
        )
        await asyncio.sleep(RETRY_DELAY_SECONDS)
        sent = await email_client.send(to=recipients, subject=subject, html_body=body)

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
) -> str:
    """Render the escalation email body as HTML.

    Phone number is included in full — these recipients are internal Tiny
    Miracles emails and the team needs the number to call the user back.
    """
    parts: List[str] = []
    parts.append("<h2>bhAI escalation triggered</h2>")
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
