#!/usr/bin/env bash
# Unload + remove the CSC daily launchd agent.
set -euo pipefail
LABEL="com.chiefsignalcat.daily"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
echo "Removed $LABEL."
