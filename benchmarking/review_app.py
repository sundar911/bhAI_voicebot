"""
Transcription Review App for Tiny Miracles team.

Launch with:
    uv run streamlit run benchmarking/review_app.py

This app allows non-technical users to:
1. Listen to audio files
2. Review and correct STT transcriptions
3. Use transliteration helper for adding Hindi text
"""

import json
import sys
from pathlib import Path
from datetime import datetime

import streamlit as st

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarking.transliteration import transliterate_sentence, transliterate_word

# Paths
DATA_DIR = ROOT / "data"
TRANSCRIPTION_DIR = DATA_DIR / "transcription_dataset"
AUDIO_DIR = DATA_DIR / "sharepoint_sync"

DOMAINS = ["helpdesk", "hr_admin", "production"]


def load_transcriptions(domain: str) -> list:
    """Load transcriptions from JSONL file."""
    jsonl_path = TRANSCRIPTION_DIR / domain / "transcriptions.jsonl"
    if not jsonl_path.exists():
        return []

    entries = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))
    return entries


def save_transcriptions(domain: str, entries: list):
    """Save transcriptions to JSONL file."""
    jsonl_path = TRANSCRIPTION_DIR / domain / "transcriptions.jsonl"
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    with open(jsonl_path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def get_audio_path(audio_file: str) -> Path:
    """Get full path to audio file."""
    # audio_file format: "domain/filename.ogg"
    return AUDIO_DIR / audio_file


def main():
    st.set_page_config(
        page_title="bhAI Transcription Review",
        page_icon="🎤",
        layout="wide"
    )

    st.title("🎤 bhAI Transcription Review")
    st.markdown("Review and correct STT transcriptions for Tiny Miracles")

    # Sidebar - Domain selection and progress
    with st.sidebar:
        st.header("Settings")

        domain = st.selectbox(
            "Select Domain",
            DOMAINS,
            format_func=lambda x: x.replace("_", " ").title()
        )

        # Load data for selected domain
        entries = load_transcriptions(domain)

        if not entries:
            st.warning(f"No transcriptions found for {domain}")
            st.stop()

        # Progress stats
        total = len(entries)
        reviewed = sum(1 for e in entries if e.get("status") == "reviewed")
        pending = total - reviewed

        st.header("Progress")
        st.metric("Total Files", total)
        col1, col2 = st.columns(2)
        col1.metric("Reviewed", reviewed, delta=None)
        col2.metric("Pending", pending, delta=None)

        progress = reviewed / total if total > 0 else 0
        st.progress(progress)
        st.caption(f"{progress:.0%} complete")

        # Filter options
        st.header("Filter")
        show_filter = st.radio(
            "Show",
            ["All", "Pending Only", "Reviewed Only"],
            index=1  # Default to pending
        )

        # Reviewer name
        st.header("Your Info")
        reviewer_name = st.text_input(
            "Your Name/Email",
            value=st.session_state.get("reviewer_name", ""),
            placeholder="e.g., priya@tinymiracles.org"
        )
        if reviewer_name:
            st.session_state["reviewer_name"] = reviewer_name

    # Filter entries
    if show_filter == "Pending Only":
        filtered_entries = [e for e in entries if e.get("status") != "reviewed"]
    elif show_filter == "Reviewed Only":
        filtered_entries = [e for e in entries if e.get("status") == "reviewed"]
    else:
        filtered_entries = entries

    if not filtered_entries:
        st.info("No entries match the current filter.")
        st.stop()

    # Entry selector
    entry_options = [
        f"{i+1}. {e['audio_file'].split('/')[-1]} {'✅' if e.get('status') == 'reviewed' else '⏳'}"
        for i, e in enumerate(filtered_entries)
    ]

    selected_idx = st.selectbox(
        "Select File to Review",
        range(len(filtered_entries)),
        format_func=lambda i: entry_options[i]
    )

    entry = filtered_entries[selected_idx]
    entry_global_idx = entries.index(entry)

    st.divider()

    # Main review area
    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("🔊 Audio")

        audio_path = get_audio_path(entry["audio_file"])
        if audio_path.exists():
            st.audio(str(audio_path))
        else:
            st.error(f"Audio file not found: {audio_path}")

        st.caption(f"File: `{entry['audio_file']}`")
        st.caption(f"STT Model: `{entry.get('stt_model', 'unknown')}`")

    with col2:
        st.subheader("📝 Original STT Output")
        st.info(entry.get("stt_draft") or "(empty)")

        if entry.get("status") == "reviewed":
            st.success(f"✅ Reviewed by: {entry.get('reviewer', 'unknown')}")

    st.divider()

    # Editable transcription
    st.subheader("✏️ Edit Transcription")

    # Pre-fill with human_reviewed if exists, else stt_draft
    current_text = entry.get("human_reviewed") or entry.get("stt_draft") or ""

    edited_text = st.text_area(
        "Edit the transcription below (fix any mistakes):",
        value=current_text,
        height=100,
        key=f"edit_{entry_global_idx}"
    )

    # Transliteration helper
    st.subheader("🔤 Transliteration Helper")
    st.caption("Need to add Hindi text? Type in English letters below:")

    col1, col2 = st.columns([2, 1])

    with col1:
        roman_input = st.text_input(
            "Type Romanized Hindi",
            placeholder="e.g., mera paisa kyun kata",
            key="roman_input"
        )

    with col2:
        if roman_input:
            # Get alternatives for the last word
            words = roman_input.split()
            if words:
                last_word = words[-1]
                alternatives = transliterate_word(last_word, top_k=5)
                if alternatives:
                    st.caption("Alternatives for last word:")
                    for alt in alternatives[:5]:
                        if st.button(alt, key=f"alt_{alt}"):
                            # This would ideally update the input, but Streamlit doesn't support that easily
                            st.info(f"Copy: {alt}")

    if roman_input:
        transliterated = transliterate_sentence(roman_input)
        st.success(f"**Transliterated:** {transliterated}")
        st.caption("Copy this and paste into the edit box above")

    st.divider()

    # Save button
    col1, col2, col3 = st.columns([1, 1, 2])

    with col1:
        if st.button("💾 Save", type="primary", use_container_width=True):
            if not reviewer_name:
                st.error("Please enter your name/email in the sidebar")
            else:
                # Update entry
                entries[entry_global_idx]["human_reviewed"] = edited_text
                entries[entry_global_idx]["status"] = "reviewed"
                entries[entry_global_idx]["reviewer"] = reviewer_name
                entries[entry_global_idx]["reviewed_at"] = datetime.now().isoformat()

                # Save to file
                save_transcriptions(domain, entries)
                st.success("✅ Saved successfully!")
                st.rerun()

    with col2:
        if st.button("⏭️ Skip", use_container_width=True):
            st.info("Skipped - moving to next")
            # Could implement auto-advance here

    with col3:
        if entry.get("status") == "reviewed":
            if st.button("🔄 Mark as Pending", use_container_width=True):
                entries[entry_global_idx]["status"] = "pending_review"
                save_transcriptions(domain, entries)
                st.success("Marked as pending")
                st.rerun()

    # Instructions
    with st.expander("📖 How to Review"):
        st.markdown("""
        ### Steps:
        1. **Listen** to the audio using the player above
        2. **Read** the original STT output (what the computer heard)
        3. **Edit** the transcription to fix any mistakes
        4. **Save** when you're done

        ### Tips:
        - Most transcriptions are 90%+ correct - just fix small errors
        - If you need to add Hindi text, use the **Transliteration Helper**
        - Type in English letters (like texting): `kyun` → क्यों
        - If audio is unclear, type `[unclear]` for that part
        - Don't guess - mark uncertain parts

        ### Transliteration Examples:
        - `mera` → मेरा
        - `paisa` → पैसा
        - `kyun` → क्यों
        - `kata` → काटा
        """)


if __name__ == "__main__":
    main()
