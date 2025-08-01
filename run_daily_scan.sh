#!/bin/bash

# Set the project directory
PROJECT_DIR="."
LOG_FILE="$PROJECT_DIR/daily_scan.log"

# Create log file with timestamp
echo "=== Daily Scan Started: $(date) ===" >> "$LOG_FILE"

# Change to project directory
cd "$PROJECT_DIR"

# Run the scan for new mods and versions
echo "Running mod scan..." >> "$LOG_FILE"
python3 manage.py scan_mods --continuous --interval 0 >> "$LOG_FILE" 2>&1

# Wait a moment for scan to complete
sleep 5

# Update README descriptions for all mods
echo "Fetching README descriptions..." >> "$LOG_FILE"
python3 manage.py update_readme_descriptions >> "$LOG_FILE" 2>&1

# Log completion
echo "=== Daily Scan Completed: $(date) ===" >> "$LOG_FILE"
echo "" >> "$LOG_FILE" 