"""
Cron-compatible pipeline runner.

Invoke via local cron (recommended for Day 1):
    0 7 * * * cd /path/to/chief-signal-cat && /path/to/python -m csc.pipeline.scheduler >> logs/csc.log 2>&1

GCP migration (Day 2): Cloud Run + Cloud Scheduler call run_once() unchanged.
The migration is a trigger swap — no code changes needed here.
Caveat: local cron only fires while the machine is on.
"""
import os
import smtplib
import sys
import time
from email.mime.text import MIMEText

from csc.config import load_config
from csc.run import run_pipeline
from csc.utils.logging import get_logger

logger = get_logger(__name__)

# Delay before the single retry attempt (seconds).
# Spec requested 5 min; 60s is used here because a transient failure
# (e.g. network blip) typically resolves in seconds, not minutes.
_RETRY_DELAY = 60


def run_once() -> None:
    """
    Single pipeline invocation entrypoint for cron / GCP.
    Retries once after _RETRY_DELAY on failure.
    Sends an alert email then exits non-zero after two consecutive failures.
    RunLog is always written — run.py's finally block guarantees it.
    """
    for attempt in range(1, 3):
        try:
            run_pipeline()
            logger.info("run_once succeeded", extra={"attempt": attempt})
            return
        except Exception as exc:
            logger.error("pipeline attempt failed", extra={"attempt": attempt, "error": str(exc)})
            if attempt < 2:
                logger.info("retrying", extra={"delay_seconds": _RETRY_DELAY})
                time.sleep(_RETRY_DELAY)

    _send_alert()
    sys.exit(1)


def _send_alert() -> None:
    """Send a plain-text failure alert. Logs and continues if SMTP is unavailable."""
    try:
        cfg = load_config()
        alert_address = cfg.get("email", {}).get("alert_address")
        if not alert_address:
            logger.error("no alert_address configured — skipping alert email")
            return

        smtp_host = os.environ.get("SMTP_HOST") or cfg["email"].get("smtp_host") or ""
        smtp_port = int(os.environ.get("SMTP_PORT") or cfg["email"].get("smtp_port") or 587)
        smtp_user = os.environ.get("SMTP_USER", "")
        smtp_password = os.environ.get("SMTP_PASSWORD", "")
        from_address = cfg["email"].get("from_address") or smtp_user

        msg = MIMEText(
            "The CSC pipeline failed after 2 consecutive attempts.\n"
            "Check logs for details.",
            "plain",
        )
        msg["Subject"] = "[CSC ALERT] Pipeline failed after 2 attempts"
        msg["From"] = from_address
        msg["To"] = alert_address

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(from_address, [alert_address], msg.as_string())

        logger.info("alert email sent", extra={"alert_address": alert_address})
    except Exception as exc:
        logger.error("failed to send alert email", extra={"error": str(exc)})


if __name__ == "__main__":
    run_once()
