#!/usr/bin/env python3
"""
Add STT transcription data from JSONL files to the SharePoint tracker CSV.

This script reads transcription data from data/transcription_dataset/*/transcriptions.jsonl
and adds them as new columns to data/Voice2Voice Final - Tracker(V2V).csv.

Columns added:
- STT Transcription: Original STT output (stt_draft)
- STT Model: Model used (e.g., saarika:v2.5)
- Human Reviewed: Corrected transcription (null if pending)
- Review Status: pending_review / reviewed / approved
- Reviewed By: Email of reviewer
- STT Timestamp: When STT was run
"""

import json
from pathlib import Path


def load_transcriptions(base_path: Path) -> dict:
    """
    Load all transcriptions from JSONL files and create a code->data mapping.

    Returns:
        Dict mapping code (case-insensitive) to transcription data
    """
    transcriptions = {}

    domains = ["helpdesk", "hr_admin", "production"]

    for domain in domains:
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

                # Extract code from audio_file path
                # e.g., "helpdesk/HD_Q_2.ogg" -> "HD_Q_2"
                audio_file = data.get("audio_file", "")
                code = Path(audio_file).stem  # Remove .ogg extension

                # Store with lowercase key for case-insensitive matching
                transcriptions[code.lower()] = {
                    "stt_draft": data.get("stt_draft", ""),
                    "stt_model": data.get("stt_model", ""),
                    "human_reviewed": data.get("human_reviewed"),
                    "status": data.get("status", ""),
                    "reviewer": data.get("reviewer"),
                    "timestamp": data.get("timestamp", ""),
                }

    return transcriptions


def process_csv(csv_path: Path, transcriptions: dict, output_path: Path):
    """
    Read CSV, add transcription columns, and write to output.
    """
    # Read the original CSV
    with open(csv_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    if not lines:
        print("Error: CSV file is empty")
        return

    # Parse header
    header = lines[0].strip()
    header_cols = header.split(";")

    # Add new column headers
    new_columns = [
        "STT Transcription",
        "STT Model",
        "Human Reviewed",
        "Review Status",
        "Reviewed By",
        "STT Timestamp"
    ]
    new_header = header + ";" + ";".join(new_columns)

    # Process data rows
    output_lines = [new_header + "\n"]
    matched_count = 0
    total_data_rows = 0

    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue

        cols = line.split(";")

        # Skip rows with #N/A or empty data (likely filler rows from Excel)
        if len(cols) < 2 or cols[1] == "" or "#N/A" in line:
            # Check if this is a data row with empty code (some valid rows have empty codes)
            if len(cols) >= 3 and cols[2] and cols[2] != "#N/A":
                # This is a valid row with empty code - keep it
                pass
            else:
                # Skip filler rows
                continue

        total_data_rows += 1

        # Get the code (column 2, index 1)
        code = cols[1].strip() if len(cols) > 1 else ""

        # Look up transcription data (case-insensitive)
        trans_data = transcriptions.get(code.lower(), {})

        if trans_data:
            matched_count += 1

        # Format values for CSV (handle None values and escape semicolons)
        def format_value(val):
            if val is None:
                return ""
            val_str = str(val)
            # Escape any semicolons in the value
            if ";" in val_str:
                val_str = f'"{val_str}"'
            return val_str

        new_values = [
            format_value(trans_data.get("stt_draft", "")),
            format_value(trans_data.get("stt_model", "")),
            format_value(trans_data.get("human_reviewed", "")),
            format_value(trans_data.get("status", "")),
            format_value(trans_data.get("reviewer", "")),
            format_value(trans_data.get("timestamp", "")),
        ]

        new_line = line + ";" + ";".join(new_values)
        output_lines.append(new_line + "\n")

    # Write output
    with open(output_path, "w", encoding="utf-8") as f:
        f.writelines(output_lines)

    print(f"Processed {total_data_rows} data rows")
    print(f"Matched {matched_count} transcriptions")
    print(f"Output written to: {output_path}")


def main():
    # Define paths
    project_root = Path(__file__).parent.parent
    transcription_base = project_root / "data" / "transcription_dataset"
    csv_path = project_root / "data" / "Voice2Voice Final - Tracker(V2V).csv"
    output_path = csv_path  # Overwrite original

    print(f"Loading transcriptions from: {transcription_base}")
    print(f"Reading CSV from: {csv_path}")

    # Load all transcriptions
    transcriptions = load_transcriptions(transcription_base)
    print(f"Loaded {len(transcriptions)} transcriptions")

    # Show some sample codes for debugging
    sample_codes = list(transcriptions.keys())[:5]
    print(f"Sample codes: {sample_codes}")

    # Process CSV
    process_csv(csv_path, transcriptions, output_path)


if __name__ == "__main__":
    main()
