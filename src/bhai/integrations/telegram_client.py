"""
Telegram Bot API client.
Handles voice download, voice/text sending, and webhook registration.

Telegram Bot API docs: https://core.telegram.org/bots/api
"""

from pathlib import Path
from typing import Any, Dict, Optional

import requests

from ..audio_utils import ensure_dir


class TelegramClient:
    """
    Client for Telegram bot messaging.

    Handles:
    - Voice file download (two-step: getFile → fetch from Telegram CDN)
    - Voice message sending (multipart upload, no public URL needed)
    - Text message sending
    - Webhook registration
    """

    def __init__(self, bot_token: str):
        if not bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN missing.")
        self.bot_token = bot_token
        self.api_base = f"https://api.telegram.org/bot{bot_token}"
        self.file_base = f"https://api.telegram.org/file/bot{bot_token}"

    def get_me(self) -> Dict[str, Any]:
        """Verify the bot token is valid by hitting getMe."""
        resp = requests.get(f"{self.api_base}/getMe", timeout=10)
        resp.raise_for_status()
        return resp.json()

    def download_voice(self, file_id: str, target_path: Path) -> Path:
        """
        Download a voice message by file_id.

        Telegram's two-step flow:
        1. POST getFile with file_id → returns file_path
        2. GET https://api.telegram.org/file/bot{TOKEN}/{file_path} → audio bytes
        """
        ensure_dir(target_path.parent)

        # Step 1: resolve file_id → file_path
        resp = requests.post(
            f"{self.api_base}/getFile",
            json={"file_id": file_id},
            timeout=30,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Telegram getFile error {resp.status_code}: {resp.text}"
            )
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram getFile not OK: {data}")
        file_path = data["result"]["file_path"]

        # Step 2: download bytes
        download_url = f"{self.file_base}/{file_path}"
        download_resp = requests.get(download_url, timeout=60)
        if download_resp.status_code >= 400:
            raise RuntimeError(
                f"Telegram media download error {download_resp.status_code}: "
                f"{download_resp.text[:200]}"
            )

        target_path.write_bytes(download_resp.content)
        return target_path

    def send_text(self, chat_id: int, body: str) -> Dict[str, Any]:
        """
        Send a text message via Telegram.

        Args:
            chat_id: Telegram chat_id (integer)
            body: Message text (Telegram supports up to 4096 chars per message)

        Returns:
            {"message_id": int, "ok": bool}
        """
        resp = requests.post(
            f"{self.api_base}/sendMessage",
            json={"chat_id": chat_id, "text": body},
            timeout=30,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Telegram sendMessage error {resp.status_code}: {resp.text}"
            )
        data = resp.json()
        return {
            "ok": data.get("ok", False),
            "message_id": data.get("result", {}).get("message_id"),
        }

    def send_voice(self, chat_id: int, audio_path: Path) -> Dict[str, Any]:
        """
        Send a voice message via Telegram.

        Telegram displays this as a "voice message" with a play button + waveform
        (not a generic file attachment). Audio must be OGG Opus.

        Args:
            chat_id: Telegram chat_id
            audio_path: Local path to OGG Opus audio file

        Returns:
            {"message_id": int, "ok": bool}
        """
        with open(audio_path, "rb") as f:
            resp = requests.post(
                f"{self.api_base}/sendVoice",
                data={"chat_id": chat_id},
                files={"voice": (audio_path.name, f, "audio/ogg")},
                timeout=60,
            )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Telegram sendVoice error {resp.status_code}: {resp.text}"
            )
        data = resp.json()
        return {
            "ok": data.get("ok", False),
            "message_id": data.get("result", {}).get("message_id"),
        }

    def set_webhook(
        self,
        url: str,
        secret_token: Optional[str] = None,
        allowed_updates: Optional[list] = None,
    ) -> Dict[str, Any]:
        """
        Register a webhook URL with Telegram.

        Once set, Telegram will POST every update to this URL.
        If secret_token is provided, Telegram includes it in the
        X-Telegram-Bot-Api-Secret-Token header for verification.
        """
        payload: Dict[str, Any] = {"url": url}
        if secret_token:
            payload["secret_token"] = secret_token
        if allowed_updates is not None:
            payload["allowed_updates"] = allowed_updates

        resp = requests.post(
            f"{self.api_base}/setWebhook",
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def delete_webhook(self) -> Dict[str, Any]:
        """Remove the webhook registration. Useful for switching to polling or migration."""
        resp = requests.post(f"{self.api_base}/deleteWebhook", timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_webhook_info(self) -> Dict[str, Any]:
        """Inspect the currently-registered webhook (URL, last error, pending updates)."""
        resp = requests.get(f"{self.api_base}/getWebhookInfo", timeout=15)
        resp.raise_for_status()
        return resp.json()
