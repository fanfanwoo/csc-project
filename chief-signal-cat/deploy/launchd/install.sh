#!/usr/bin/env bash
# Install + load the CSC launchd agents: daily pipeline (07:00) + heartbeat (12:00).
# Generates the real plist from the template using this machine's python + repo path,
# then (re-)bootstraps it. Re-run safely — it reloads. Activates daily autonomous runs.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKDIR="$(cd "$HERE/../.." && pwd)"          # chief-signal-cat/
LABELS=(com.chiefsignalcat.daily com.chiefsignalcat.heartbeat)
DOMAIN="gui/$(id -u)"

# Interpreter choice: $CSC_PYTHON > repo .venv > python3 on PATH.
# Prefer the venv: the global python3 may carry wheels for the wrong architecture
# (an x86_64-only pydantic_core broke every run from 2026-07-04 — launchd starts
# universal binaries as arm64, while a Rosetta shell happily imports x86_64 wheels).
if [[ -n "${CSC_PYTHON:-}" ]]; then
  PYTHON="$CSC_PYTHON"
elif [[ -x "$WORKDIR/.venv/bin/python" ]]; then
  PYTHON="$WORKDIR/.venv/bin/python"
else
  PYTHON="$(python3 -c 'import sys; print(sys.executable)')"
fi

# Heartbeat is stdlib-only and deliberately runs on the system python, independent of
# the venv: if the venv breaks, the pipeline dies and the heartbeat must still alert.
HEARTBEAT_PYTHON="${CSC_HEARTBEAT_PYTHON:-/usr/bin/python3}"

cd "$WORKDIR"
# Import the real entrypoint natively (arm64 on Apple Silicon), the way launchd will.
ARCH_PREFIX=()
if [[ "$(sysctl -n hw.optional.arm64 2>/dev/null || echo 0)" == "1" ]]; then
  ARCH_PREFIX=(arch -arm64)
fi
if ! ${ARCH_PREFIX[@]+"${ARCH_PREFIX[@]}"} "$PYTHON" -c 'import csc.pipeline.scheduler' 2>/dev/null; then
  echo "ERROR: '$PYTHON' cannot import csc.pipeline.scheduler natively." >&2
  echo "       Create the venv (python3 -m venv .venv && .venv/bin/pip install -r requirements.txt) or set CSC_PYTHON." >&2
  exit 1
fi

if ! ${ARCH_PREFIX[@]+"${ARCH_PREFIX[@]}"} "$HEARTBEAT_PYTHON" -c 'import csc.tools.check_heartbeat' 2>/dev/null; then
  echo "ERROR: '$HEARTBEAT_PYTHON' cannot import csc.tools.check_heartbeat (needs Python 3.9+)." >&2
  echo "       Set CSC_HEARTBEAT_PYTHON to another interpreter." >&2
  exit 1
fi

mkdir -p "$WORKDIR/logs" "$HOME/Library/LaunchAgents"
for LABEL in "${LABELS[@]}"; do
  PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
  sed -e "s|__PYTHON__|$PYTHON|g" -e "s|__HEARTBEAT_PYTHON__|$HEARTBEAT_PYTHON|g" -e "s|__WORKDIR__|$WORKDIR|g" \
    "$HERE/$LABEL.plist.template" > "$PLIST"
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  launchctl bootstrap "$DOMAIN" "$PLIST"
  echo "Loaded $LABEL"
done

echo "  schedule: pipeline daily 07:00, heartbeat daily 12:00 (local)"
echo "  python  : $PYTHON (pipeline), $HEARTBEAT_PYTHON (heartbeat)"
echo "  workdir : $WORKDIR"
echo "  logs    : $WORKDIR/logs/csc.scheduler.log, csc.heartbeat.log"
echo "Verify  : launchctl print $DOMAIN/com.chiefsignalcat.daily"
echo "Test now: launchctl kickstart $DOMAIN/com.chiefsignalcat.daily   (runs immediately — sends a real email)"
