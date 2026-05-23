from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from csc.pipeline.send_email import send_email
from csc.schemas.briefs import Brief

NOW = datetime.now(timezone.utc)
CFG = {
    "provider": "smtp",
    "smtp_host": "smtp.example.com",
    "smtp_port": 587,
    "from_address": "signal-cat@example.com",
    "recipients": ["team@example.com"],
}
BRIEF = Brief(
    run_id="run-1",
    date_range="2025-05-20",
    generated_at=NOW,
    one_line_readout="ASIC guidance creates compliance obligations for auto lenders.",
    markdown_body="# Brief\n\nContent here.",
    top_signal_ids=["abc"],
)


def test_send_email_calls_smtp():
    mock_smtp = MagicMock()
    with (
        patch("csc.pipeline.send_email.smtplib.SMTP") as mock_smtp_cls,
        patch.dict("os.environ", {"SMTP_USER": "user", "SMTP_PASSWORD": "pass"}),
    ):
        mock_smtp_cls.return_value.__enter__.return_value = mock_smtp
        send_email(BRIEF, CFG)

    mock_smtp.sendmail.assert_called_once()
    call_args = mock_smtp.sendmail.call_args
    assert "team@example.com" in call_args[0][1]


def test_email_subject_contains_date_and_readout():
    captured = {}

    def fake_sendmail(from_, to, msg_str):
        captured["msg"] = msg_str

    mock_smtp_instance = MagicMock()
    mock_smtp_instance.sendmail.side_effect = fake_sendmail

    with (
        patch("csc.pipeline.send_email.smtplib.SMTP") as mock_smtp_cls,
        patch.dict("os.environ", {"SMTP_USER": "u", "SMTP_PASSWORD": "p"}),
    ):
        mock_smtp_cls.return_value.__enter__.return_value = mock_smtp_instance
        send_email(BRIEF, CFG)

    assert "2025-05-20" in captured["msg"]
    assert "[CSC]" in captured["msg"]
