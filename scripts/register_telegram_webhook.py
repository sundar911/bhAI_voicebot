"""
One-shot helper to register the Telegram webhook URL.

Run this once after deploying the Telegram webhook (or any time the
public URL changes). Reads TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET,
and the target URL from the .env file or CLI args.

Usage:
    uv run python scripts/register_telegram_webhook.py https://your-railway-url.up.railway.app

Or to inspect the current webhook without changing it:
    uv run python scripts/register_telegram_webhook.py --info

Or to delete the webhook (e.g. before switching back to polling):
    uv run python scripts/register_telegram_webhook.py --delete
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bhai.config import load_config
from src.bhai.integrations.telegram_client import TelegramClient


def main() -> int:
    config = load_config()

    if not config.telegram_bot_token:
        print(
            "ERROR: TELEGRAM_BOT_TOKEN not set in .env. "
            "Get it from @BotFather and put it in .env first.",
            file=sys.stderr,
        )
        return 1

    client = TelegramClient(bot_token=config.telegram_bot_token)
    args = sys.argv[1:]

    if not args:
        print(__doc__)
        return 0

    if args[0] == "--info":
        info = client.get_webhook_info()
        print(json.dumps(info, indent=2))
        return 0

    if args[0] == "--delete":
        result = client.delete_webhook()
        print(json.dumps(result, indent=2))
        return 0

    base_url = args[0].rstrip("/")
    webhook_url = f"{base_url}/telegram/webhook"

    if not config.telegram_webhook_secret:
        print(
            "WARNING: TELEGRAM_WEBHOOK_SECRET not set — registering without secret token. "
            "This means anyone who knows the URL can POST to it. "
            "Set TELEGRAM_WEBHOOK_SECRET in .env before going live.",
            file=sys.stderr,
        )

    # Check that the bot token is valid first
    me = client.get_me()
    if not me.get("ok"):
        print(f"ERROR: getMe failed: {me}", file=sys.stderr)
        return 1
    bot = me["result"]
    print(f"Registering webhook for @{bot['username']} ({bot['first_name']})")
    print(f"  URL:    {webhook_url}")
    print(f"  Secret: {'set' if config.telegram_webhook_secret else '(none)'}")

    result = client.set_webhook(
        url=webhook_url,
        secret_token=config.telegram_webhook_secret or None,
        # Subscribe only to messages and edited messages — skip channel posts, etc.
        allowed_updates=["message", "edited_message"],
    )
    print(json.dumps(result, indent=2))

    if result.get("ok"):
        print("\n✓ Webhook registered. Send a voice note to your bot to test.")
        return 0
    print("\n✗ Webhook registration failed. See response above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
