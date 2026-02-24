#!/usr/bin/env python3
"""
Batch transcription pipeline: SharePoint → Sarvam STT → SharePoint Excel.

Downloads new audio files from the Voice2Voice SharePoint folder,
runs Sarvam STT on each, and appends results to the
Live_Transcription_Sundar worksheet.

Usage:
    # Dry run — list files without processing
    python scripts/sharepoint_batch_transcribe.py --dry-run

    # Process all new files
    python scripts/sharepoint_batch_transcribe.py

    # Process only specific folders
    python scripts/sharepoint_batch_transcribe.py --folders Helpdesk HR-Admin
"""

import argparse
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# Force unbuffered stdout so device code prompt appears immediately
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

# Add src to path for imports
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bhai.config import DATA_DIR, load_config
from src.bhai.integrations.sharepoint import SharePointClient
from src.bhai.stt.sarvam_stt import SarvamSTT

# SharePoint folder names → local JSONL domain keys
FOLDER_TO_DOMAIN = {
    "Grievance": "grievance",
    "Helpdesk": "helpdesk",
    "HR-Admin": "hr_admin",
    "Impact": "impact",
    "NextGen": "nextgen",
    "Production": "production",
}

# Path to the Voice2Voice folder in the SharePoint document library
# This will be discovered/confirmed during --dry-run
VOICE2VOICE_FOLDER = "Voice2Voice"

# Path to the Excel workbook (relative to drive root)
WORKBOOK_PATH = "Voice2Voice/Voice2Voice Final - Tracker.xlsx"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch transcribe SharePoint audio files and update Excel tracker"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files and show what would be processed, without downloading or transcribing",
    )
    parser.add_argument(
        "--folders",
        nargs="+",
        choices=list(FOLDER_TO_DOMAIN.keys()),
        default=list(FOLDER_TO_DOMAIN.keys()),
        help="Which Voice2Voice sub-folders to process (default: all)",
    )
    parser.add_argument(
        "--drive",
        default=None,
        help="SharePoint document library name (omit for default drive)",
    )
    parser.add_argument(
        "--v2v-path",
        default=VOICE2VOICE_FOLDER,
        help=f"Path to Voice2Voice folder in the drive (default: {VOICE2VOICE_FOLDER})",
    )
    parser.add_argument(
        "--workbook-path",
        default=WORKBOOK_PATH,
        help=f"Path to the Excel workbook in the drive (default: {WORKBOOK_PATH})",
    )
    parser.add_argument(
        "--list-drives",
        action="store_true",
        help="List all document libraries and exit (useful for discovery)",
    )
    return parser.parse_args()


def load_processed_filenames() -> set[str]:
    """Load filenames already transcribed from local JSONL files."""
    processed = set()
    transcription_dir = DATA_DIR / "transcription_dataset"

    if not transcription_dir.exists():
        return processed

    for jsonl_path in transcription_dir.glob("*/transcriptions.jsonl"):
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                # audio_file is like "helpdesk/HD_Q_2.ogg" — extract just the filename
                audio_file = entry.get("audio_file", "")
                filename = Path(audio_file).name
                if filename:
                    processed.add(filename.lower())

    return processed


def append_to_jsonl(domain: str, entry: dict) -> None:
    """Append a transcription entry to the local JSONL file."""
    jsonl_dir = DATA_DIR / "transcription_dataset" / domain
    jsonl_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = jsonl_dir / "transcriptions.jsonl"
    with open(jsonl_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main() -> None:
    args = parse_args()
    config = load_config()

    if not config.azure_tenant_id or not config.azure_app_client_id:
        print("Error: AZURE_TENANT_ID and AZURE_APP_CLIENT_ID must be set in .env")
        sys.exit(1)

    # Initialize SharePoint client
    sp = SharePointClient(
        tenant_id=config.azure_tenant_id,
        client_id=config.azure_app_client_id,
        hostname=config.sharepoint_hostname,
    )

    print("Authenticating with SharePoint...")
    sp.authenticate()
    print("Authenticated successfully.\n")

    # Discovery mode
    if args.list_drives:
        drives = sp.list_drives()
        print("Available document libraries:")
        for d in drives:
            print(f"  - {d['name']} (id: {d['id']})")
        return

    # Set drive if specified
    if args.drive:
        sp.get_drive_id(args.drive)
    else:
        sp.get_drive_id()

    # Load already-processed files
    processed = load_processed_filenames()
    print(f"Already processed: {len(processed)} files\n")

    # Collect new files from each folder
    all_new_files: list[tuple[str, str, dict]] = []  # (folder_name, domain, file_info)

    for folder_name in args.folders:
        domain = FOLDER_TO_DOMAIN[folder_name]
        folder_path = f"{args.v2v_path}/{folder_name}"

        print(f"Scanning {folder_path}...")
        try:
            audio_files = sp.list_audio_files(folder_path)
        except Exception as e:
            print(f"  Warning: could not list {folder_path}: {e}")
            continue

        new_files = [
            f for f in audio_files
            if f["name"].lower() not in processed
        ]
        print(f"  Found {len(audio_files)} audio files, {len(new_files)} new")

        for f in new_files:
            all_new_files.append((folder_name, domain, f))

    print(f"\nTotal new files to process: {len(all_new_files)}")

    if args.dry_run:
        print("\n--- DRY RUN — no files will be downloaded or transcribed ---\n")
        for folder_name, domain, f in all_new_files:
            size_kb = f.get("size", 0) / 1024
            print(f"  [{folder_name}] {f['name']} ({size_kb:.0f} KB)")

        # Also show current Excel sheet state
        print(f"\nChecking worksheet in {args.workbook_path}...")
        try:
            values = sp.read_excel_worksheet_values(args.workbook_path)
            if values:
                print(f"  Existing rows: {len(values)} (including header)")
                if values[0]:
                    print(f"  Columns: {values[0]}")
            else:
                print("  Sheet is empty")
        except Exception as e:
            print(f"  Could not read worksheet: {e}")
        return

    if not all_new_files:
        print("Nothing to process.")
        return

    # Initialize STT
    work_dir = ROOT / ".bhai_temp" / "sp_batch_stt"
    work_dir.mkdir(parents=True, exist_ok=True)
    stt = SarvamSTT(config, work_dir=work_dir)

    # Read existing Excel state to figure out column layout
    print(f"\nReading existing Excel sheet...")
    try:
        existing_values = sp.read_excel_worksheet_values(args.workbook_path)
        if existing_values and existing_values[0]:
            header = existing_values[0]
            print(f"  Columns: {header}")
            existing_row_count = len(existing_values)
        else:
            header = None
            existing_row_count = 0
    except Exception as e:
        print(f"  Could not read sheet: {e}")
        header = None
        existing_row_count = 0

    # Process files
    excel_rows: list[list[str]] = []
    success_count = 0
    error_count = 0

    with tempfile.TemporaryDirectory(prefix="bhai_sp_") as tmp_dir:
        tmp_path = Path(tmp_dir)

        for i, (folder_name, domain, file_info) in enumerate(all_new_files):
            filename = file_info["name"]
            file_id = file_info["id"]
            print(f"\n[{i+1}/{len(all_new_files)}] {folder_name}/{filename}")

            # Download
            local_file = tmp_path / filename
            try:
                sp.download_file(file_id, local_file)
                print(f"  Downloaded ({local_file.stat().st_size / 1024:.0f} KB)")
            except Exception as e:
                print(f"  Download failed: {e}")
                error_count += 1
                continue

            # Transcribe
            stt_error = None
            try:
                result = stt.transcribe(local_file)
                transcript = result["text"]
                print(f"  STT: {transcript[:80]}...")
                status = "pending_review"
            except Exception as e:
                print(f"  STT error: {e}")
                transcript = None
                stt_error = str(e)
                status = "error"
                error_count += 1

            timestamp = datetime.now().isoformat()

            # Build JSONL entry
            jsonl_entry = {
                "audio_file": f"{domain}/{filename}",
                "stt_model": stt.model_name,
                "stt_draft": transcript,
                "human_reviewed": None,
                "final": None,
                "status": status,
                "reviewer": None,
                "timestamp": timestamp,
            }
            if stt_error:
                jsonl_entry["error"] = stt_error

            # Save to local JSONL
            append_to_jsonl(domain, jsonl_entry)

            # Build Excel row
            # Default columns: Department, File Name, STT Transcription, STT Model, Status, Timestamp
            excel_row = [
                folder_name,           # Department (using SharePoint folder name)
                filename,              # File Name
                transcript or "",      # STT Transcription
                stt.model_name,        # STT Model
                status,                # Status
                timestamp,             # Timestamp
            ]
            excel_rows.append(excel_row)

            if transcript:
                success_count += 1

    # Batch append to Excel
    if excel_rows:
        print(f"\nAppending {len(excel_rows)} rows to Excel...")
        try:
            sp.append_excel_rows(args.workbook_path, excel_rows)
            print("  Done!")
        except Exception as e:
            print(f"  Excel update failed: {e}")
            print("  Rows were saved to local JSONL files.")

    print(f"\nSummary: {success_count} transcribed, {error_count} errors, {len(all_new_files)} total")


if __name__ == "__main__":
    main()
