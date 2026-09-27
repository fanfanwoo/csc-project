"""
Heartbeat — alert when no brief has been produced recently.

The scheduler's own failure alert only fires if the pipeline gets far enough to
retry. A crash at import time (wrong interpreter, broken wheel) or a job launchd
never starts produces no alert at all — 85 days went silent that way from
2026-07-04. This check is independent of the pipeline: it only looks at the
newest file mtime in data/briefs/ and emails the configured alert_address if
nothing is newer than --max-age-hours (default 36).

Exits 0 when fresh, 1 when stale (so `launchctl print` shows the last result).

    python3 -m csc.tools.check_heartbeat
    python3 -m csc.tools.check_heartbeat --max-age-hours 48 --briefs-dir /path/to/briefs
    python3 -m csc.tools.check_heartbeat --no-email      # report only
"""

import argparse
import sys
import time
from pathlib import Path

from csc.utils.logging import get_logger

logger = get_logger(__name__)

DEFAULT_MAX_AGE_HOURS = 36.0


def newest_brief(briefs_dir: Path) -> Path | None:
    """Newest non-hidden file in briefs_dir by mtime, or None if there is none."""
    if not briefs_dir.is_dir():
        return None
    files = [p for p in briefs_dir.iterdir() if p.is_file() and not p.name.startswith(".")]
    return max(files, key=lambda p: p.stat().st_mtime, default=None)


def check(briefs_dir: Path, max_age_hours: float, now: float | None = None) -> tuple[bool, Path | None, float | None]:
    """Return (fresh, newest_path, age_hours). age_hours is None when there is no brief."""
    now = time.time() if now is None else now
    newest = newest_brief(briefs_dir)
    if newest is None:
        return False, None, None
    age_hours = (now - newest.stat().st_mtime) / 3600
    return age_hours <= max_age_hours, newest, age_hours


def format_status(fresh: bool, newest: Path | None, age_hours: float | None, max_age_hours: float) -> str:
    if newest is None:
        return f"STALE: no briefs found (threshold {max_age_hours:g}h)"
    state = "OK" if fresh else "STALE"
    return f"{state}: newest brief {newest.name} is {age_hours:.1f}h old (threshold {max_age_hours:g}h)"


def send_alert(status: str, briefs_dir: Path) -> None:
    """Email the alert_address from config/email.yaml. Imports lazily so the check itself stays light."""
    from csc.config import load_config
    from csc.pipeline.send_email import send_plain_text

    email_cfg = load_config().get("email", {})
    if not email_cfg.get("alert_address"):
        logger.error("no alert_address configured — skipping heartbeat alert")
        return
    body = (
        f"{status}\n\n"
        f"Briefs dir: {briefs_dir.resolve()}\n"
        "The daily pipeline has not produced a brief. Check:\n"
        "  launchctl print gui/$(id -u)/com.chiefsignalcat.daily\n"
        "  tail -50 logs/csc.scheduler.log\n"
    )
    send_plain_text(subject="[CSC ALERT] No brief in the last day and a half", body=body, cfg=email_cfg)
    logger.info("heartbeat alert sent", extra={"alert_address": email_cfg["alert_address"]})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Alert if no recent brief exists.")
    parser.add_argument("--briefs-dir", default="data/briefs", help="dir the pipeline saves briefs to")
    parser.add_argument("--max-age-hours", type=float, default=DEFAULT_MAX_AGE_HOURS)
    parser.add_argument("--no-email", action="store_true", help="report only, never send the alert")
    args = parser.parse_args(argv)

    briefs_dir = Path(args.briefs_dir)
    fresh, newest, age_hours = check(briefs_dir, args.max_age_hours)
    status = format_status(fresh, newest, age_hours, args.max_age_hours)
    print(status)
    if fresh:
        return 0
    if not args.no_email:
        send_alert(status, briefs_dir)
    return 1


if __name__ == "__main__":
    sys.exit(main())
