#!/usr/bin/env bash
# Unload + remove the CSC launchd agents (daily pipeline + heartbeat).
set -euo pipefail
for LABEL in com.chiefsignalcat.daily com.chiefsignalcat.heartbeat; do
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
  echo "Removed $LABEL."
done
