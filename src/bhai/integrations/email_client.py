"""
Gmail API email client for escalation notifications.

Uses OAuth 2.0 with a long-lived refresh token captured by
scripts/gmail_oauth_setup.py. Sends via the Gmail API (HTTPS to
gmail.googleapis.com) rather than SMTP — Railway and most modern PaaS
block outbound SMTP on 25/465/587 to prevent abuse, so SMTP is a dead
end in cloud deployments.

The client is intentionally minimal: one method, returns bool, never
raises. Callers (escalation handler) decide what to do with a False
return. The Google access token is auto-refreshed by Credentials when
needed, so we hold a single Credentials instance for the process
lifetime.
"""

import asyncio
import base64
import logging
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import List, Optional

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger("bhai.integrations.email")

# Send-only scope — least privilege. Matches what scripts/gmail_oauth_setup.py
# requests when capturing the refresh token. Mismatch will fail at send time.
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


@dataclass
class EmailClient:
    """Async wrapper around the Gmail API users.messages.send endpoint.

    The Gmail API SDK is sync, so we wrap each send in asyncio.to_thread
    to avoid blocking the event loop (same pattern as resilience/worker.py).
    """

    client_id: str
    client_secret: str
    refresh_token: str
    sender_email: str
    _creds: Optional[Credentials] = field(default=None, init=False, repr=False)

    def _get_credentials(self) -> Credentials:
        """Lazily build Credentials; reuse across sends so the access token
        cache + auto-refresh works."""
        if self._creds is None:
            self._creds = Credentials(
                token=None,  # forces a refresh on first use
                refresh_token=self.refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self.client_id,
                client_secret=self.client_secret,
                scopes=GMAIL_SCOPES,
            )
        return self._creds

    async def send(self, to: List[str], subject: str, html_body: str) -> bool:
        """Send an HTML email via Gmail API. Returns True on success, False
        on any failure.

        Failures are logged with the error string but no PII (recipient
        addresses are internal Tiny Miracles emails — we log count, not
        addresses).
        """
        if not (self.client_id and self.client_secret and self.refresh_token):
            logger.warning(
                "EmailClient.send called with incomplete OAuth credentials — skipping"
            )
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
        creds = self._get_credentials()
        if not creds.valid:
            creds.refresh(GoogleAuthRequest())

        msg = EmailMessage()
        msg["From"] = self.sender_email
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        msg.set_content("This email requires an HTML-capable client.")
        msg.add_alternative(html_body, subtype="html")

        # Gmail API expects URL-safe base64 of the raw RFC 822 message.
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")

        # cache_discovery=False suppresses the file-cache warning under
        # google-api-python-client when running in environments without a
        # writable HOME (Railway containers).
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
