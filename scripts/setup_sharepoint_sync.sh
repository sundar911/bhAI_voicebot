#!/bin/bash
# Setup script for SharePoint sync using rclone
# Run this once to configure rclone for SharePoint access

set -e

echo "=== bhAI SharePoint Sync Setup ==="
echo ""

# Check if rclone is installed
if ! command -v rclone &> /dev/null; then
    echo "rclone not found. Installing via Homebrew..."
    brew install rclone
fi

echo "rclone version: $(rclone version | head -1)"
echo ""

# Configure rclone for SharePoint/OneDrive
echo "Starting rclone configuration..."
echo ""
echo "When prompted:"
echo "1. Select 'onedrive' as the storage type"
echo "2. Leave client_id and client_secret blank (press Enter)"
echo "3. Choose 'global' for region"
echo "4. Say 'y' to auto config (browser will open)"
echo "5. Login with: sundarr.nitt@gmail.com"
echo "6. Choose the shared folder when prompted"
echo ""
echo "Press Enter to continue..."
read

rclone config create sharepoint_bhai onedrive

echo ""
echo "=== Configuration Complete ==="
echo ""
echo "Test the connection with:"
echo "  rclone lsd sharepoint_bhai:"
echo ""
echo "Then run the sync script:"
echo "  ./scripts/sync_sharepoint.sh"
echo ""
echo "To set up automatic hourly sync:"
echo "  ./scripts/setup_auto_sync.sh"
