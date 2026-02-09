# Getting Started with bhAI Transcription Review

A step-by-step guide for Tiny Miracles team members.

**Time needed:** ~15 minutes for first-time setup, then 30 seconds to start the app each day.

---

## Step 1: Install Required Software (First Time Only)

You need three programs: **Python** (runs the code), **Git** (saves your work), and **uv** (installs dependencies).

### For Windows

**Install Python:**
1. Go to https://www.python.org/downloads/
2. Click the yellow "Download Python" button
3. Run the installer
4. **IMPORTANT:** Check the box that says "Add Python to PATH"
5. Click "Install Now"

**Install Git:**
1. Go to https://git-scm.com/download/win
2. Download and run the installer
3. Use all default settings, just keep clicking "Next"

**Install uv:**
1. Open Command Prompt (press Windows key, type `cmd`, press Enter)
2. Paste this command and press Enter:
   ```
   pip install uv
   ```

### For Mac

1. Open Terminal (press Cmd+Space, type `Terminal`, press Enter)

2. If you don't have Homebrew, install it first:
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```

3. Install Python and Git:
   ```bash
   brew install python git
   ```

4. Install uv:
   ```bash
   pip install uv
   ```

---

## Step 2: Get the Code (First Time Only)

Open Terminal (Mac) or Command Prompt (Windows) and run:

```bash
git clone https://github.com/sundar911/bhAI_voicebot.git
```

Then go into the folder:

```bash
cd bhAI_voicebot
```

Install the dependencies:

```bash
uv sync --extra review
```

This may take a few minutes. Wait until it finishes.

---

## Step 3: Start the Review App

Every time you want to review transcriptions, run this command:

```bash
uv run streamlit run benchmarking/review_app.py
```

A browser window will open automatically. If not, go to: http://localhost:8501

**To stop the app:** Press `Ctrl+C` in the terminal.

---

## Step 4: Create Your Branch (Recommended)

Before making changes, create your own branch. This keeps your work separate and organized.

```bash
git checkout -b hr-admin-transcriptions
```

Or use a name for your domain:
- `production-transcriptions`
- `helpdesk-transcriptions`
- `review/your-name-batch-001`

---

## Step 5: Save Your Work to Git

After reviewing transcriptions, save your changes:

```bash
git add data/transcription_dataset/
git commit -m "Reviewed transcriptions - [Your Name]"
git push -u origin hr-admin-transcriptions
```

Replace `[Your Name]` with your actual name and `hr-admin-transcriptions` with your branch name.

**After the first push**, you can use the shorter command:
```bash
git add data/transcription_dataset/
git commit -m "More reviews - [Your Name]"
git push
```

---

## Daily Workflow (Quick Reference)

```bash
# 1. Go to the project folder
cd bhAI_voicebot

# 2. Get latest changes (start of day)
git pull

# 3. Start the app
uv run streamlit run benchmarking/review_app.py

# 4. After reviewing, save your work
git add data/transcription_dataset/
git commit -m "Reviewed [X] files - [Your Name]"
git push
```

---

## Troubleshooting

### "Command not found: uv"
Run `pip install uv` again. If that fails, try `pip3 install uv`.

### "Command not found: git"
You need to install Git first. See Step 1 above.

### "Permission denied" errors
On Mac, try adding `sudo` before the command:
```bash
sudo pip install uv
```

### Browser doesn't open automatically
Manually go to http://localhost:8501 in your browser.

### "Port already in use"
Another app is using port 8501. Either close that app, or run:
```bash
uv run streamlit run benchmarking/review_app.py --server.port 8502
```

### Audio files not playing
Make sure the audio files exist in `data/sharepoint_sync/`. Ask your team lead if files are missing.

### Git says "Please tell me who you are"
Run these commands with your info:
```bash
git config --global user.email "your.email@tinymiracles.org"
git config --global user.name "Your Name"
```

---

## Using the Review App

For detailed instructions on using the app itself, see [review_instructions.md](review_instructions.md).

Quick summary:
1. Select your domain (HR Admin, Helpdesk, Production) in the sidebar
2. Enter your name
3. Select an audio file from the dropdown
4. Listen to the audio and fix any mistakes in the transcription
5. Click Save

---

## Getting Help

1. Check this guide first
2. Ask your team lead
3. Contact the development team

For app usage questions, see [review_instructions.md](review_instructions.md).
