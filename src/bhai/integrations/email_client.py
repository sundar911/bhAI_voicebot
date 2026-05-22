"""
Resend (HTTPS API) email client for escalation notifications.

Resend's HTTPS API works from Railway and other PaaS that block outbound
SMTP. SDK is sync, so we wrap each call in asyncio.to_thread to avoid
stalling the event loop (same pattern as resilience/worker.py).

The client is intentionally minimal: one method, returns bool, never
raises. Callers (escalation handler) decide what to do with a False
return.

Note on sender domain: until you verify a sender domain in the Resend
dashboard, you can only send FROM `onboarding@resend.dev` and only TO
the email address used to sign up. After verifying tinymiracles.com
(DNS records: SPF, DKIM, optional DMARC), you can set RESEND_FROM_EMAIL
to anything @tinymiracles.com.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import List

import resend

logger = logging.getLogger("bhai.integrations.email")


@dataclass
class EmailClient:
    """Async wrapper around the Resend HTTPS API."""

    api_key: str
    from_email: str

    async def send(self, to: List[str], subject: str, html_body: str) -> bool:
        """Send an HTML email. Returns True on success, False on any failure.

        Failures are logged with the error string but no PII (recipient
        addresses are internal Tiny Miracles emails — we log count, not
        addresses).
        """
        if not self.api_key:
            logger.warning("EmailClient.send called with no api_key — skipping")
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
        # Set the module-level api_key on every call to be safe in case
        # multiple clients with different keys ever coexist in one process.
        resend.api_key = self.api_key
        resend.Emails.send(
            {
                "from": self.from_email,
                "to": to,
                "subject": subject,
                "html": html_body,
            }
        )
