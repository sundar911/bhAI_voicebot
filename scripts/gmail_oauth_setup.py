"""
One-time helper to capture a Gmail OAuth refresh token.

Usage:
    1. Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET in .env (from Google Cloud
       Console → APIs & Services → Credentials → your Desktop OAuth client).
    2. Run: uv run python scripts/gmail_oauth_setup.py
    3. A browser tab opens. Sign in as the Workspace account that will SEND
       escalation emails (e.g. sundar@tinymiracles.com). Approve the scope.
    4. Copy the printed refresh_token into your .env as GMAIL_REFRESH_TOKEN
       (and into Railway env vars for prod/dev environments).

You only need to do this ONCE per sender account. Refresh tokens for Internal
Workspace OAuth apps don't expire (unlike External Testing apps which expire
after 7 days). Token will be revoked if you delete the OAuth client or revoke
access in the user's Google account.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

# Scope: send-only. Don't grant gmail.modify or full gmail — least privilege.
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env", override=False)

    client_id = os.getenv("GMAIL_CLIENT_ID", "")
    client_secret = os.getenv("GMAIL_CLIENT_SECRET", "")
    if not (client_id and client_secret):
        print(
            "ERROR: GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET must be set in .env\n"
            "Get these from Google Cloud Console → APIs & Services → Credentials\n"
            "→ create OAuth client ID (Desktop app type).",
            file=sys.stderr,
        )
        return 1

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(
        port=0,
        prompt="consent",  # forces refresh_token return even if previously authorized
        access_type="offline",
    )

    if not creds.refresh_token:
        print(
            "ERROR: No refresh_token returned. This usually means you've already "
            "authorized this client before. Revoke access at "
            "https://myaccount.google.com/permissions and rerun.",
            file=sys.stderr,
        )
        return 1

    print("\n" + "=" * 70)
    print("SUCCESS. Add these to your .env (and to Railway env vars):")
    print("=" * 70)
    print(f"GMAIL_REFRESH_TOKEN={creds.refresh_token}")
    print(
        f"GMAIL_SENDER_EMAIL={creds.id_token.get('email') if creds.id_token else '<paste-sender-email>'}"
    )
    print("=" * 70)
    print(
        "\nThe refresh token never expires (Internal Workspace apps). Keep it "
        "secret — anyone with it can send mail as the authorized user."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
