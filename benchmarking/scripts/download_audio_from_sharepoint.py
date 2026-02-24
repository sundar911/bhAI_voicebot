#!/usr/bin/env python3
"""
Download audio files from SharePoint for benchmarking.
Thin wrapper around the existing SharePointClient.

Usage:
    python benchmarking/scripts/download_audio_from_sharepoint.py
    python benchmarking/scripts/download_audio_from_sharepoint.py --folders Helpdesk HR-Admin
    python benchmarking/scripts/download_audio_from_sharepoint.py --dry-run
"""

import argparse
import os
import sys
from pathlib import Path

# Force unbuffered stdout so device code prompt appears immediately
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bhai.integrations.sharepoint import SharePointClient

VOICE2VOICE_FOLDER = "Voice2Voice"

FOLDER_TO_DOMAIN: dict[str, str] = {
    "Grievance":  "grievance",
    "Helpdesk":   "helpdesk",
    "HR-Admin":   "hr_admin",
    "Impact":     "impact",
    "NextGen":    "nextgen",
    "Production": "production",
}

DATA_DIR = ROOT / "data"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download audio from SharePoint")
    parser.add_argument(
        "--folders",
        nargs="+",
        choices=list(FOLDER_TO_DOMAIN.keys()),
        default=["Helpdesk", "HR-Admin", "Production"],
        help="Which Voice2Voice sub-folders to download (default: Helpdesk HR-Admin Production)",
    )
    parser.add_argument("--dry-run", action="store_true", help="List files without downloading")
    parser.add_argument("--drive", default=None, help="SharePoint document library name")
    parser.add_argument("--v2v-path", default=VOICE2VOICE_FOLDER, help="Voice2Voice folder path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    tenant_id = os.getenv("AZURE_TENANT_ID", "")
    client_id = os.getenv("AZURE_APP_CLIENT_ID", "")
    hostname = os.getenv("SHAREPOINT_HOSTNAME", "tinymiraclesnl.sharepoint.com")

    if not tenant_id or not client_id:
        print("Error: AZURE_TENANT_ID and AZURE_APP_CLIENT_ID must be set.")
        print("In Colab, use: from google.colab import userdata")
        sys.exit(1)

    sp = SharePointClient(tenant_id=tenant_id, client_id=client_id, hostname=hostname)
    print("Authenticating with SharePoint...")
    sp.authenticate()
    print("Authenticated.\n")

    if args.drive:
        sp.get_drive_id(args.drive)
    else:
        sp.get_drive_id()

    total_downloaded = 0

    for folder_name in args.folders:
        domain = FOLDER_TO_DOMAIN[folder_name]
        folder_path = f"{args.v2v_path}/{folder_name}"
        local_dir = DATA_DIR / "sharepoint_sync" / domain

        print(f"Scanning {folder_path}...")
        try:
            audio_files = sp.list_audio_files(folder_path)
        except Exception as e:
            print(f"  Warning: could not list {folder_path}: {e}")
            continue

        # Skip files already downloaded
        existing = {f.name.lower() for f in local_dir.glob("*") if f.is_file()} if local_dir.exists() else set()
        new_files = [f for f in audio_files if f["name"].lower() not in existing]

        print(f"  Found {len(audio_files)} audio files, {len(new_files)} new")

        if args.dry_run:
            for f in new_files:
                print(f"    {f['name']} ({f.get('size', 0) / 1024:.0f} KB)")
            continue

        local_dir.mkdir(parents=True, exist_ok=True)
        for f in new_files:
            dest = local_dir / f["name"]
            try:
                sp.download_file(f["id"], dest)
                total_downloaded += 1
                print(f"  Downloaded: {f['name']}")
            except Exception as e:
                print(f"  Failed: {f['name']}: {e}")

    if not args.dry_run:
        print(f"\nDone. Downloaded {total_downloaded} new files.")


if __name__ == "__main__":
    main()
