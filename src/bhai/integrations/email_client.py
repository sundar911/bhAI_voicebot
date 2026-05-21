"""
Gmail SMTP email client for escalation notifications.

Authenticates against smtp.gmail.com using a Google Workspace user
(e.g. bhai@tinymiracles.com) and a 16-char app-specific password.
Generate one at: https://myaccount.google.com/apppasswords (2FA must be on).

We use stdlib smtplib (no extra dep) and wrap the blocking send in
asyncio.to_thread so the event loop isn't stalled.

The client is intentionally minimal: one method, returns bool, never raises.
Callers (escalation handler) decide what to do with a False return.
"""

import asyncio
import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import List

logger = logging.getLogger("bhai.integrations.email")


@dataclass
class EmailClient:
    """Gmail SMTP client wrapped for async use.

    Defaults target Gmail Workspace on port 587 (STARTTLS). For 465 (implicit
    SSL) set port=465 — the client picks SMTP_SSL automatically.
    """

    username: str
    app_password: str
    from_address: str
    host: str = "smtp.gmail.com"
    port: int = 587
    timeout: int = 30

    async def send(self, to: List[str], subject: str, html_body: str) -> bool:
        """Send an HTML email. Returns True on success, False on any failure.

        Failures are logged with the error string but no PII (recipient
        addresses are internal Tiny Miracles emails — we log count, not
        addresses).
        """
        if not (self.username and self.app_password):
            logger.warning("EmailClient.send called with no credentials — skipping")
            return False
        if not to:
            logger.warning("EmailClient.send called with empty recipient list")
            return False

        try:
            await asyncio.to_thread(self._send_sync, to, subject, html_body)
            logger.info(
                "Escalation email sent (recipients=%d, subject_len=%d)",
                len(to),
                len(subject),
            )
            return True
        except Exception as e:
            logger.error("Escalation email send failed: %s", e)
            return False

    def _send_sync(self, to: List[str], subject: str, html_body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.from_address
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        # Set a minimal plain-text fallback then add the HTML alternative.
        msg.set_content("This email requires an HTML-capable client.")
        msg.add_alternative(html_body, subtype="html")

        if self.port == 465:
            with smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout) as s:
                s.login(self.username, self.app_password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as s:
                s.starttls()
                s.login(self.username, self.app_password)
                s.send_message(msg)
