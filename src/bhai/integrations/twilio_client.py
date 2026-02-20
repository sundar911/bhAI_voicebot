"""
Twilio WhatsApp client.
Handles media download and message sending via Twilio API.
"""

from pathlib import Path
from typing import Any, Dict

import requests
from twilio.rest import Client

from ..audio_utils import ensure_dir


class TwilioWhatsAppClient:
    """
    Client for WhatsApp messaging via Twilio.

    Handles:
    - Media download from Twilio URLs (Basic Auth)
    - Audio message sending via Twilio SDK
    """

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        whatsapp_number: str,
    ):
        """
        Initialize Twilio WhatsApp client.

        Args:
            account_sid: Twilio Account SID
            auth_token: Twilio Auth Token
            whatsapp_number: Twilio WhatsApp sender number
                             (format: "whatsapp:+14155238886")
        """
        if not account_sid:
            raise RuntimeError("TWILIO_ACCOUNT_SID missing.")
        if not auth_token:
            raise RuntimeError("TWILIO_AUTH_TOKEN missing.")
        if not whatsapp_number:
            raise RuntimeError("TWILIO_WHATSAPP_NUMBER missing.")

        self.account_sid = account_sid
        self.auth_token = auth_token
        self.whatsapp_number = whatsapp_number
        self.client = Client(account_sid, auth_token)

    def download_media(self, media_url: str, target_path: Path) -> Path:
        """
        Download media from a Twilio media URL.

        Twilio media URLs require HTTP Basic Auth (SID:Token).

        Args:
            media_url: Twilio media URL (from webhook MediaUrl0)
            target_path: Local path to save downloaded file

        Returns:
            Path to downloaded file
        """
        ensure_dir(target_path.parent)
        response = requests.get(
            media_url,
            auth=(self.account_sid, self.auth_token),
            timeout=60,
        )

        if response.status_code >= 400:
            raise RuntimeError(
                f"Twilio media download error {response.status_code}: "
                f"{response.text}"
            )

        target_path.write_bytes(response.content)
        return target_path

    def send_audio_message(
        self,
        to_number: str,
        media_url: str,
    ) -> Dict[str, Any]:
        """
        Send an audio message via Twilio WhatsApp.

        Args:
            to_number: Recipient in Twilio format
                       (e.g., "whatsapp:+919876543210")
            media_url: Publicly accessible URL for the audio file

        Returns:
            Dictionary with message SID and status
        """
        message = self.client.messages.create(
            from_=self.whatsapp_number,
            to=to_number,
            media_url=[media_url],
        )

        return {
            "sid": message.sid,
            "status": message.status,
        }
