"""
WhatsApp Business API client.
Handles media upload/download and message sending via Meta Graph API.
"""

from pathlib import Path
from typing import Any, Dict

import requests

from ..audio_utils import ensure_dir


class WhatsAppClient:
    """
    Client for WhatsApp Business API via Meta Graph API.

    Handles:
    - Media URL retrieval and download
    - Media upload
    - Audio message sending
    """

    def __init__(
        self,
        token: str,
        phone_number_id: str,
        api_version: str = "v22.0"
    ):
        """
        Initialize WhatsApp client.

        Args:
            token: Meta WhatsApp Business API token
            phone_number_id: WhatsApp Business phone number ID
            api_version: Graph API version
        """
        if not token:
            raise RuntimeError("META_WA_TOKEN missing.")
        if not phone_number_id:
            raise RuntimeError("META_PHONE_NUMBER_ID missing.")

        self.token = token
        self.phone_number_id = phone_number_id
        self.api_version = api_version
        self.base_url = f"https://graph.facebook.com/{api_version}"

    def _headers(self) -> Dict[str, str]:
        """Get authorization headers."""
        return {"Authorization": f"Bearer {self.token}"}

    def get_media_url(self, media_id: str) -> Dict[str, Any]:
        """
        Get media URL from media ID.

        Args:
            media_id: WhatsApp media ID

        Returns:
            Media metadata including URL
        """
        url = f"{self.base_url}/{media_id}"
        response = requests.get(url, headers=self._headers(), timeout=30)

        if response.status_code >= 400:
            raise RuntimeError(
                f"Media lookup error {response.status_code}: {response.text}"
            )

        return response.json()

    def download_media(self, media_url: str, target_path: Path) -> Path:
        """
        Download media from WhatsApp.

        Args:
            media_url: URL to download from
            target_path: Local path to save file

        Returns:
            Path to downloaded file
        """
        ensure_dir(target_path.parent)
        response = requests.get(media_url, headers=self._headers(), timeout=60)

        if response.status_code >= 400:
            raise RuntimeError(
                f"Media download error {response.status_code}: {response.text}"
            )

        target_path.write_bytes(response.content)
        return target_path

    def upload_media(
        self,
        audio_path: Path,
        mime_type: str = "audio/ogg"
    ) -> str:
        """
        Upload media to WhatsApp.

        Args:
            audio_path: Path to audio file
            mime_type: MIME type of the file

        Returns:
            Media ID for the uploaded file
        """
        url = f"{self.base_url}/{self.phone_number_id}/media"
        data = {
            "messaging_product": "whatsapp",
            "type": mime_type,
        }

        with audio_path.open("rb") as f:
            files = {"file": (audio_path.name, f, mime_type)}
            response = requests.post(
                url,
                headers=self._headers(),
                data=data,
                files=files,
                timeout=60
            )

        if response.status_code >= 400:
            raise RuntimeError(
                f"Media upload error {response.status_code}: {response.text}"
            )

        payload = response.json()
        media_id = payload.get("id")

        if not media_id:
            raise RuntimeError(f"Media upload missing id: {payload}")

        return media_id

    def send_audio(self, to_number: str, media_id: str) -> Dict[str, Any]:
        """
        Send audio message to a WhatsApp number.

        Args:
            to_number: Recipient phone number
            media_id: WhatsApp media ID of audio to send

        Returns:
            Send response from API
        """
        url = f"{self.base_url}/{self.phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "audio",
            "audio": {"id": media_id},
        }

        response = requests.post(
            url,
            headers={**self._headers(), "Content-Type": "application/json"},
            json=payload,
            timeout=60
        )

        if response.status_code >= 400:
            raise RuntimeError(
                f"Send audio error {response.status_code}: {response.text}"
            )

        return response.json()
