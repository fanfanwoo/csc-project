import smtplib
import os
from email.mime.text import MIMEText

from csc.schemas.briefs import Brief
from csc.utils.logging import get_logger

logger = get_logger(__name__)


def send_email(brief: Brief, cfg: dict) -> None:
    subject = f"[CSC] Brief — {brief.date_range} — {brief.one_line_readout[:80]}"
    body = brief.markdown_body

    if cfg.get("provider") == "sendgrid":
        _send_sendgrid(subject, body, cfg)
    else:
        _send_smtp(subject, body, cfg)


def _send_smtp(subject: str, body: str, cfg: dict) -> None:
    from_address = cfg.get("from_address") or os.environ.get("SMTP_USER", "")
    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = ", ".join(cfg["recipients"])

    smtp_host = os.environ.get("SMTP_HOST") or cfg.get("smtp_host") or ""
    smtp_port = int(os.environ.get("SMTP_PORT") or cfg.get("smtp_port") or 587)
    smtp_user = os.environ["SMTP_USER"]
    smtp_password = os.environ["SMTP_PASSWORD"]
    from_address = cfg.get("from_address") or smtp_user

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(from_address, cfg["recipients"], msg.as_string())
        logger.info("email sent", extra={"recipients": cfg["recipients"], "subject": subject})
    except Exception as exc:
        logger.error("email send failed", extra={"error": str(exc)})
        raise


def _send_sendgrid(subject: str, body: str, cfg: dict) -> None:
    raise NotImplementedError("SendGrid provider not yet implemented")
