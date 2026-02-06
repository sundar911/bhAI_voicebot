#!/bin/bash
# Sync audio files from SharePoint to local data directory
# Run manually or via scheduled task

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOCAL_PATH="$PROJECT_ROOT/data/sharepoint_sync"
LOG_FILE="$LOCAL_PATH/sync.log"

# rclone remote name (configured in setup_sharepoint_sync.sh)
REMOTE="sharepoint_bhai"

# SharePoint folder paths (adjust these to match your SharePoint structure)
# These are the folder names in your shared SharePoint folder
HELPDESK_REMOTE="helpdesk"
HR_ADMIN_REMOTE="hr-admin"
PRODUCTION_REMOTE="production"

echo "=== bhAI SharePoint Sync ===" | tee -a "$LOG_FILE"
echo "Started at: $(date)" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# Create local directories if they don't exist
mkdir -p "$LOCAL_PATH/helpdesk"
mkdir -p "$LOCAL_PATH/hr_admin"
mkdir -p "$LOCAL_PATH/production"

# Sync helpdesk folder
echo "Syncing helpdesk..." | tee -a "$LOG_FILE"
rclone sync "$REMOTE:$HELPDESK_REMOTE" "$LOCAL_PATH/helpdesk" \
    --include "*.ogg" \
    --include "*.wav" \
    --include "*.mp3" \
    --include "*.m4a" \
    --include "*.opus" \
    --progress \
    --log-file "$LOG_FILE" \
    --log-level INFO \
    2>&1 | tee -a "$LOG_FILE"

# Sync hr-admin folder
echo "Syncing hr_admin..." | tee -a "$LOG_FILE"
rclone sync "$REMOTE:$HR_ADMIN_REMOTE" "$LOCAL_PATH/hr_admin" \
    --include "*.ogg" \
    --include "*.wav" \
    --include "*.mp3" \
    --include "*.m4a" \
    --include "*.opus" \
    --progress \
    --log-file "$LOG_FILE" \
    --log-level INFO \
    2>&1 | tee -a "$LOG_FILE"

# Sync production folder
echo "Syncing production..." | tee -a "$LOG_FILE"
rclone sync "$REMOTE:$PRODUCTION_REMOTE" "$LOCAL_PATH/production" \
    --include "*.ogg" \
    --include "*.wav" \
    --include "*.mp3" \
    --include "*.m4a" \
    --include "*.opus" \
    --progress \
    --log-file "$LOG_FILE" \
    --log-level INFO \
    2>&1 | tee -a "$LOG_FILE"

echo "" | tee -a "$LOG_FILE"
echo "Sync completed at: $(date)" | tee -a "$LOG_FILE"
echo "==========================" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# Count synced files
echo "Files synced:"
echo "  helpdesk:   $(find "$LOCAL_PATH/helpdesk" -type f | wc -l | tr -d ' ') files"
echo "  hr_admin:   $(find "$LOCAL_PATH/hr_admin" -type f | wc -l | tr -d ' ') files"
echo "  production: $(find "$LOCAL_PATH/production" -type f | wc -l | tr -d ' ') files"
