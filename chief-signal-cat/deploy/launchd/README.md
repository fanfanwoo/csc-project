# Daily schedule (macOS launchd)

Runs the CSC pipeline once a day via the existing `csc.pipeline.scheduler`
(retry-once + failure-alert email already built in). Nothing here runs until you
install it.

## Install (activates daily runs)

```bash
cd chief-signal-cat
bash deploy/launchd/install.sh
```

This detects your `python3` (must import `csc` — the one you run `pytest` with),
fills the template with your python + repo paths, writes
`~/Library/LaunchAgents/com.chiefsignalcat.daily.plist`, and `launchctl load`s it.
Fires **daily at 07:00 local**.

## What it does each run

Full pipeline: fetch → … → verify → score → summarise → **emails the brief** to the
configured recipients, and writes `RunLog.metrics` to `data/logs/`. So once active it
incurs **daily Gemini cost + a daily email**.

## Verify / test / remove

```bash
launchctl list | grep chiefsignalcat            # confirm loaded
launchctl start com.chiefsignalcat.daily        # run NOW (sends a real email)
tail -f logs/csc.scheduler.log                  # watch output
bash deploy/launchd/uninstall.sh                # unload + remove
```

## Caveats

- **Laptop must be awake.** launchd fires the job on the next wake if the Mac was
  asleep at 07:00 (runs once, does not stack missed days).
- Credentials come from `chief-signal-cat/.env` (loaded by `csc.config`), so the
  agent needs no extra environment.
- The generated plist has machine-specific absolute paths and is **not committed**
  (only this template + scripts are). Re-run `install.sh` if your python or path moves.

## Watch the accumulating runs

```bash
python3 -m csc.tools.run_metrics_report     # publisher depth / filter / enrich / Phase 0+3
python3 -m csc.tools.review_recurrence      # corroboration-agent trigger (exact-URL recurrence)
```
