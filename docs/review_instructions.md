# How to Review Transcriptions

This guide helps Tiny Miracles team members review and correct audio transcriptions.

## Prerequisites

Before using the review app, complete the initial setup.

**First time?** Follow the complete guide: [SETUP_FOR_TINY.md](SETUP_FOR_TINY.md)

**Already set up?** Continue to Quick Start below.

---

## Quick Start

### Step 1: Open the Review App

Run this command in your terminal:

```bash
uv run streamlit run benchmarking/review_app.py
```

A browser window will open automatically. If not, go to: http://localhost:8501

### Step 2: Select Your Domain

In the sidebar, choose which domain to review:
- **Helpdesk** - Government document/scheme questions
- **HR Admin** - Salary, leave, benefits questions
- **Production** - Factory floor, machines, chai/breakfast questions

### Step 3: Enter Your Name

Type your name or email in the sidebar. This tracks who reviewed each file.

### Step 4: Review Each File

For each audio file:

1. **Listen** - Click the play button to hear the audio
2. **Read** - Check the transcription (already filled in by computer)
3. **Edit** - Fix any mistakes directly in the text box
4. **Save** - Click the green Save button

## Editing Tips

### Most Transcriptions Are Already 90% Correct

The computer has already done most of the work. You just need to fix small errors like:
- Wrong words
- Missing words
- Spelling mistakes

### Adding Hindi Text

If you need to add or replace Hindi text:

1. Use the **Transliteration Helper** at the bottom
2. Type in English letters (like texting)
3. Copy the Hindi result and paste it

**Examples:**
| You type | Computer shows |
|----------|----------------|
| mera | मेरा |
| paisa | पैसा |
| kyun | क्यों |
| chutti | छुट्टी |
| salary | सैलरी |

### If Audio Is Unclear

- Type `[unclear]` for parts you can't understand
- Don't guess - it's better to mark as unclear
- Example: `मेरा [unclear] कब मिलेगा`

### Multiple Options

Sometimes the transliteration shows multiple options (e.g., for "kya"):
- क्या
- क्यू
- क्यों

Click the one that matches what you heard.

## Progress Tracking

The sidebar shows:
- **Total Files** - How many files in this domain
- **Reviewed** - How many you've completed
- **Pending** - How many are left
- **Progress bar** - Visual progress

## Filtering

Use the filter options to:
- **Pending Only** - Show only files that need review (default)
- **Reviewed Only** - Check your completed work
- **All** - See everything

## Common Questions

### Q: What if I make a mistake?
A: Just edit the file again. Click "Mark as Pending" to review it again later.

### Q: Can I skip a file?
A: Yes, click "Skip" to move on. You can come back to it later.

### Q: How long does each file take?
A: Most files take 30 seconds to 2 minutes. Just fix the mistakes you hear.

### Q: What if the original transcription is completely wrong?
A: Delete it and type the correct text. Use the transliteration helper for Hindi.

### Q: Do I need to type in Hindi keyboard?
A: No! Type in English letters (like SMS/WhatsApp) and the computer converts it.

## Getting Help

If you have questions:
1. Check this guide
2. Ask your team lead
3. Contact the development team

## Technical Notes (For Developers)

The review app:
- Reads from `data/transcription_dataset/{domain}/transcriptions.jsonl`
- Saves `human_reviewed` field (preserves original `stt_draft`)
- Tracks reviewer name and timestamp
- Uses AI4Bharat transliteration (offline, no API needed)

To install dependencies:
```bash
uv sync --extra review
```

---

## Saving Your Work to Git

After reviewing transcriptions, save your changes to git so others can see them.

### Create Your Branch (First Time)

```bash
git checkout -b hr-admin-transcriptions
```

Or use a name for your domain: `production-transcriptions`, `helpdesk-transcriptions`

### Save Your Changes

```bash
# Add your changes
git add data/transcription_dataset/

# Commit with a message
git commit -m "Reviewed [X] files - [Your Name]"

# Push to remote
git push -u origin hr-admin-transcriptions
```

After the first push, you can use the shorter command:
```bash
git add data/transcription_dataset/
git commit -m "More reviews - [Your Name]"
git push
```

### Daily Workflow

```bash
# Start of day: get latest changes
git pull

# Start the app
uv run streamlit run benchmarking/review_app.py

# After reviewing: save your work
git add data/transcription_dataset/
git commit -m "Reviewed files - [Your Name]"
git push
```
