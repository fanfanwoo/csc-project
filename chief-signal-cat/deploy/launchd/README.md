# Daily schedule (macOS launchd)

Two agents:

- `com.chiefsignalcat.daily` — runs the CSC pipeline once a day at **07:00** via
  `csc.pipeline.scheduler` (retry-once + failure-alert email built in).
- `com.chiefsignalcat.heartbeat` — runs `csc.tools.check_heartbeat` daily at **12:00**;
  emails `alert_address` if no brief in `data/briefs/` is newer than 36h. Catches
  failures the scheduler can't report (e.g. a crash at import time).

Nothing here runs until you install it.

## Install (activates daily runs)

```bash
cd chief-signal-cat
bash deploy/launchd/install.sh
```

Interpreter: `$CSC_PYTHON` if set, else `chief-signal-cat/.venv/bin/python`, else
`python3` on PATH. It must import `csc.pipeline.scheduler` **natively** — install.sh
checks under `arch -arm64` on Apple Silicon, because launchd starts universal
pythons as arm64 while a Rosetta shell imports x86_64 wheels fine. (An x86_64-only
`pydantic_core` in the global python3 broke every run from 2026-07-04 unnoticed.)

It fills both templates, writes them to `~/Library/LaunchAgents/`, and
`launchctl bootout`/`bootstrap`s them (re-run safe).

## What it does each run

Full pipeline: fetch → … → verify → score → summarise → **emails the brief** to the
configured recipients, and writes `RunLog.metrics` to `data/logs/`. So once active it
incurs **daily Gemini cost + a daily email**.

## Verify / test / remove

```bash
launchctl print gui/$(id -u)/com.chiefsignalcat.daily   # state, runs, last exit code
launchctl kickstart gui/$(id -u)/com.chiefsignalcat.daily   # run NOW (sends a real email)
tail -f logs/csc.scheduler.log                  # pipeline output
tail -f logs/csc.heartbeat.log                  # heartbeat output
python3 -m csc.tools.check_heartbeat --no-email # check freshness without alerting
bash deploy/launchd/uninstall.sh                # unload + remove both
```

## Caveats

- **Laptop must be awake.** launchd fires the job on the next wake if the Mac was
  asleep at 07:00 (runs once, does not stack missed days).
- Credentials come from `chief-signal-cat/.env` (loaded by `csc.config`), so the
  agent needs no extra environment.
- `last exit code = 1` with a growing `runs` count means the job fires but fails —
  read `logs/csc.scheduler.log`.
- The generated plist has machine-specific absolute paths and is **not committed**
  (only this template + scripts are). Re-run `install.sh` if your python or path moves.

## Watch the accumulating runs

```bash
python3 -m csc.tools.run_metrics_report     # publisher depth / filter / enrich / Phase 0+3
python3 -m csc.tools.review_recurrence      # corroboration-agent trigger (exact-URL, distinct days)
```
