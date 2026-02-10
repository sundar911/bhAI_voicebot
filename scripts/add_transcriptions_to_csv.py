#!/usr/bin/env python3
"""
Generate a fresh transcription tracker CSV from JSONL files.

This script reads transcription data from data/transcription_dataset/*/transcriptions.jsonl
and generates a clean CSV at data/transcription_tracker.csv.

Columns:
- Department: Helpdesk, HR/Admin, Production
- File Name: Audio file basename (e.g., HD_Q_2.ogg)
- STT Transcription: Original STT output (stt_draft)
- STT Model: Model used (e.g., saarika:v2.5)
- Human Reviewed: Corrected transcription (empty if null)
- Final: Final approved transcription (empty if null)
- Status: pending_review / reviewed / approved
- Reviewer: Email of reviewer (empty if null)
- Timestamp: When STT was run
"""

import csv
import json
from pathlib import Path


# Map folder names to display names
DOMAIN_NAMES = {
    "helpdesk": "Helpdesk",
    "hr_admin": "HR/Admin",
    "production": "Production",
}


def load_transcriptions(base_path: Path) -> list[dict]:
    """
    Load all transcriptions from JSONL files.

    Returns:
        List of transcription records with department info added
    """
    records = []

    for domain, display_name in DOMAIN_NAMES.items():
        jsonl_path = base_path / domain / "transcriptions.jsonl"
        if not jsonl_path.exists():
            print(f"Warning: {jsonl_path} not found, skipping")
            continue

        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                data = json.loads(line)

                # Extract file name from audio_file path
                # e.g., "helpdesk/HD_Q_2.ogg" -> "HD_Q_2.ogg"
                audio_file = data.get("audio_file", "")
                file_name = Path(audio_file).name

                records.append({
                    "department": display_name,
                    "file_name": file_name,
                    "stt_transcription": data.get("stt_draft", ""),
                    "stt_model": data.get("stt_model", ""),
                    "human_reviewed": data.get("human_reviewed") or "",
                    "final": data.get("final") or "",
                    "status": data.get("status", ""),
                    "reviewer": data.get("reviewer") or "",
                    "timestamp": data.get("timestamp", ""),
                })

    return records


def write_csv(records: list[dict], output_path: Path):
    """
    Write records to CSV file.
    """
    # Sort by department, then file name
    department_order = {"Helpdesk": 0, "HR/Admin": 1, "Production": 2}
    records.sort(key=lambda r: (department_order.get(r["department"], 99), r["file_name"]))

    # Define column headers
    fieldnames = [
        "Department",
        "File Name",
        "STT Transcription",
        "STT Model",
        "Human Reviewed",
        "Final",
        "Status",
        "Reviewer",
        "Timestamp",
    ]

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)

        # Write header
        writer.writerow(fieldnames)

        # Write data rows
        for record in records:
            writer.writerow([
                record["department"],
                record["file_name"],
                record["stt_transcription"],
                record["stt_model"],
                record["human_reviewed"],
                record["final"],
                record["status"],
                record["reviewer"],
                record["timestamp"],
            ])

    print(f"Written {len(records)} records to: {output_path}")


def main():
    # Define paths
    project_root = Path(__file__).parent.parent
    transcription_base = project_root / "data" / "transcription_dataset"
    output_path = project_root / "data" / "transcription_tracker.csv"

    print(f"Loading transcriptions from: {transcription_base}")

    # Load all transcriptions
    records = load_transcriptions(transcription_base)
    print(f"Loaded {len(records)} transcriptions")

    # Show counts per department
    dept_counts = {}
    for record in records:
        dept = record["department"]
        dept_counts[dept] = dept_counts.get(dept, 0) + 1
    for dept, count in sorted(dept_counts.items()):
        print(f"  {dept}: {count}")

    # Write CSV
    write_csv(records, output_path)


if __name__ == "__main__":
    main()
