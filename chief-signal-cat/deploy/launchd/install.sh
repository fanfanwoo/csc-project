#!/usr/bin/env bash
# Install + load the CSC daily launchd agent (07:00 local).
# Generates the real plist from the template using this machine's python + repo path,
# then loads it. Re-run safely — it reloads. Activates daily autonomous runs.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKDIR="$(cd "$HERE/../.." && pwd)"          # chief-signal-cat/
LABEL="com.chiefsignalcat.daily"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

# Use the python that can import csc (same interpreter you run pytest with).
PYTHON="$(python3 -c 'import sys; print(sys.executable)')"

cd "$WORKDIR"
if ! "$PYTHON" -c 'import csc.run' 2>/dev/null; then
  echo "ERROR: '$PYTHON' cannot import csc. Activate the right venv / install deps, then re-run." >&2
  exit 1
fi

mkdir -p "$WORKDIR/logs" "$HOME/Library/LaunchAgents"
sed -e "s|__PYTHON__|$PYTHON|g" -e "s|__WORKDIR__|$WORKDIR|g" \
  "$HERE/$LABEL.plist.template" > "$PLIST"

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "Loaded $LABEL — daily 07:00 local."
echo "  python : $PYTHON"
echo "  workdir: $WORKDIR"
echo "  logs   : $WORKDIR/logs/csc.scheduler.log"
echo "Verify : launchctl list | grep chiefsignalcat"
echo "Test now: launchctl start $LABEL   (runs immediately — sends a real email)"
