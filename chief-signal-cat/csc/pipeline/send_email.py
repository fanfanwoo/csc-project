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
    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = cfg["from_address"]
    msg["To"] = ", ".join(cfg["recipients"])

    try:
        with smtplib.SMTP(cfg["smtp_host"], cfg.get("smtp_port", 587)) as server:
            server.starttls()
            server.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            server.sendmail(cfg["from_address"], cfg["recipients"], msg.as_string())
        logger.info("email sent", extra={"recipients": cfg["recipients"], "subject": subject})
    except Exception as exc:
        logger.error("email send failed", extra={"error": str(exc)})
        raise


def _send_sendgrid(subject: str, body: str, cfg: dict) -> None:
    raise NotImplementedError("SendGrid provider not yet implemented")
