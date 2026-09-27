"""
Heartbeat — alert when no brief has been produced recently.

The scheduler's own failure alert only fires if the pipeline gets far enough to
retry. A crash at import time (wrong interpreter, broken wheel) or a job launchd
never starts produces no alert at all — 85 days went silent that way from
2026-07-04. This check is independent of the pipeline: it only looks at the
newest file mtime in data/briefs/ and emails the configured alert_address if
nothing is newer than --max-age-hours (default 36).

**Stdlib-only, Python 3.9+.** launchd runs it with /usr/bin/python3 so it keeps
working when the project venv or its wheels are broken — exactly when it's needed.
It therefore does not import csc.config (PyYAML) or csc.pipeline.send_email
(pydantic via schemas); it reads config/email.yaml and .env itself and sends via
smtplib, mirroring send_email's SMTP transport.

Exits 0 when fresh, 1 when stale (so `launchctl print` shows the last result).

    python3 -m csc.tools.check_heartbeat
    python3 -m csc.tools.check_heartbeat --max-age-hours 48 --briefs-dir /path/to/briefs
    python3 -m csc.tools.check_heartbeat --no-email      # report only
"""
from __future__ import annotations

import argparse
import logging
import os
import smtplib
import sys
import time
from email.mime.text import MIMEText
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent      # chief-signal-cat/
EMAIL_YAML = _ROOT / "config" / "email.yaml"
ENV_FILE = _ROOT / ".env"

DEFAULT_MAX_AGE_HOURS = 36.0

logger = logging.getLogger(__name__)
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)


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


# ── config (no PyYAML) ────────────────────────────────────────

def _scalar(raw: str) -> str:
    """Strip an inline comment and surrounding quotes from a YAML scalar."""
    value = raw.strip()
    if value[:1] in ("'", '"'):
        quote = value[0]
        end = value.find(quote, 1)
        return value[1:end] if end != -1 else value[1:]
    return value.split(" #", 1)[0].strip()


def read_email_cfg(path: Path | None = None) -> dict:
    """Scalar keys under the top-level `email:` block of config/email.yaml.

    Deliberately minimal — only `key: value` lines, which is all the alert needs
    (provider, smtp_host, smtp_port, from_address, alert_address). List entries
    (recipients) and nested blocks are skipped.
    """
    path = EMAIL_YAML if path is None else path
    cfg: dict = {}
    in_email = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line[0].isspace():
            in_email = stripped.split("#", 1)[0].strip() == "email:"
            continue
        if not in_email or stripped.startswith("- ") or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        value = _scalar(value)
        if value:
            cfg[key.strip()] = value
    return cfg


def load_dotenv(path: Path | None = None) -> None:
    """Same rules as csc.config._load_dotenv: KEY=VALUE lines, never override os.environ."""
    path = ENV_FILE if path is None else path
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


# ── alert ─────────────────────────────────────────────────────

def _send_smtp(subject: str, body: str, recipients: list[str], cfg: dict) -> None:
    """Mirror of csc.pipeline.send_email._send_smtp (env overrides config)."""
    smtp_host = os.environ.get("SMTP_HOST") or cfg.get("smtp_host") or ""
    smtp_port = int(os.environ.get("SMTP_PORT") or cfg.get("smtp_port") or 587)
    smtp_user = os.environ["SMTP_USER"]
    smtp_password = os.environ["SMTP_PASSWORD"]
    from_address = cfg.get("from_address") or smtp_user

    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = ", ".join(recipients)

    with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(from_address, recipients, msg.as_string())


def send_alert(status: str, briefs_dir: Path) -> None:
    """Email alert_address from config/email.yaml over SMTP. Credentials come from .env."""
    load_dotenv()
    email_cfg = read_email_cfg()
    alert_address = email_cfg.get("alert_address")
    if not alert_address:
        logger.error("no alert_address configured — skipping heartbeat alert")
        return
    if email_cfg.get("provider", "smtp") != "smtp":
        logger.error("heartbeat alert only supports provider smtp, got %s", email_cfg.get("provider"))
        return
    body = (
        f"{status}\n\n"
        f"Briefs dir: {briefs_dir.resolve()}\n"
        "The daily pipeline has not produced a brief. Check:\n"
        "  launchctl print gui/$(id -u)/com.chiefsignalcat.daily\n"
        "  tail -50 logs/csc.scheduler.log\n"
    )
    _send_smtp("[CSC ALERT] No brief in the last day and a half", body, [alert_address], email_cfg)
    logger.info("heartbeat alert sent to %s", alert_address)


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
