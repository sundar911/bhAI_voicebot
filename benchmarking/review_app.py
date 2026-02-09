"""
Transcription Review App for Tiny Miracles team.

Launch with:
    uv run streamlit run benchmarking/review_app.py

This app allows non-technical users to:
1. Listen to audio files
2. Review and correct STT transcriptions
3. Use on-screen Devanagari keyboard for Hindi/Marathi text
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

# Import the custom Devanagari editor component
from benchmarking.components import devanagari_editor

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

    # Editable transcription with integrated Devanagari keyboard
    st.subheader("✏️ Edit Transcription")

    # Get initial text
    initial_text = entry.get("human_reviewed") or entry.get("stt_draft") or ""

    # Use the custom Devanagari editor component
    # This provides cursor-aware character insertion
    st.caption("**Step 1:** Edit in the editor below. Click to place cursor, then use keyboard buttons.")
    devanagari_editor(
        initial_value=initial_text,
        height=450,
        key=f"editor_{entry_global_idx}"
    )

    # Text area for final save (user copies from editor above)
    st.caption("**Step 2:** After editing, click 'Copy Text' above, then paste here:")

    # Session state for the save text area
    save_key = f"save_textarea_{entry_global_idx}"
    if save_key not in st.session_state:
        st.session_state[save_key] = initial_text

    edited_text = st.text_area(
        "Paste edited text here before saving:",
        height=100,
        key=save_key,
        label_visibility="collapsed"
    )

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
        1. **Listen** to the audio
        2. **Edit** in the editor - click to place cursor, click keyboard buttons to insert
        3. **Copy** - click the green "Copy Text" button
        4. **Paste** - click in the text box below and Ctrl+V / Cmd+V
        5. **Save** - click the Save button

        ### Using the Editor:
        - **Click in the text** to place your cursor
        - **Type directly** or **click keyboard buttons** - they insert at cursor!
        - Expand "Consonants", "Extras", "Numbers" as needed

        ### Quick Markers:
        - `[unclear]` - Cannot understand this part
        - `[noise]` - Background noise
        - `[overlap]` - Multiple speakers

        ### Why copy-paste?
        The fancy editor runs in an iframe for cursor support. We need to copy the text out to save it.
        """)


if __name__ == "__main__":
    main()
