"""
Tests for csc.pipeline.scheduler — retry/alert/exit branching.
run_pipeline is mocked; time.sleep is patched so the 60s retry delay is instant.
"""
import logging
import pytest
from unittest.mock import MagicMock, patch, call


@pytest.fixture(autouse=True)
def no_retry_sleep(monkeypatch):
    monkeypatch.setattr("csc.pipeline.scheduler.time.sleep", lambda _: None)


# ── run_once ──────────────────────────────────────────────────

def test_run_once_succeeds_first_attempt():
    """Pipeline succeeds on first try — no alert, no sys.exit."""
    with patch("csc.pipeline.scheduler.run_pipeline") as mock_run, \
         patch("csc.pipeline.scheduler._send_alert") as mock_alert:
        from csc.pipeline.scheduler import run_once
        run_once()

    mock_run.assert_called_once()
    mock_alert.assert_not_called()


def test_run_once_retries_on_first_failure():
    """Pipeline fails first attempt, succeeds second — alert not called."""
    results = [RuntimeError("transient"), None]

    def side_effect():
        r = results.pop(0)
        if isinstance(r, Exception):
            raise r

    with patch("csc.pipeline.scheduler.run_pipeline", side_effect=side_effect) as mock_run, \
         patch("csc.pipeline.scheduler._send_alert") as mock_alert:
        from csc.pipeline.scheduler import run_once
        run_once()

    assert mock_run.call_count == 2
    mock_alert.assert_not_called()


def test_run_once_exits_after_two_failures():
    """Two consecutive failures → _send_alert called once, SystemExit(1)."""
    with patch("csc.pipeline.scheduler.run_pipeline", side_effect=RuntimeError("down")), \
         patch("csc.pipeline.scheduler._send_alert") as mock_alert:
        from csc.pipeline.scheduler import run_once
        with pytest.raises(SystemExit) as exc_info:
            run_once()

    assert exc_info.value.code == 1
    mock_alert.assert_called_once()


# ── _send_alert ───────────────────────────────────────────────

_EMAIL_CFG = {
    "email": {
        "provider": "smtp",
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "from_address": "csc@example.com",
        "alert_address": "alert@example.com",
    }
}


def test_send_alert_swallows_smtp_error():
    """SMTP failure in send_plain_text is caught — _send_alert does not raise."""
    with patch("csc.pipeline.scheduler.load_config", return_value=_EMAIL_CFG), \
         patch("csc.pipeline.scheduler.send_plain_text", side_effect=OSError("smtp timeout")):
        from csc.pipeline.scheduler import _send_alert
        _send_alert()  # must not raise


def test_send_alert_logs_sendgrid_not_implemented(caplog):
    """provider=sendgrid raises NotImplementedError — caught, logged with SendGrid diagnosis."""
    sendgrid_cfg = {
        "email": {**_EMAIL_CFG["email"], "provider": "sendgrid"}
    }
    with patch("csc.pipeline.scheduler.load_config", return_value=sendgrid_cfg), \
         patch("csc.pipeline.scheduler.send_plain_text",
               side_effect=NotImplementedError("SendGrid provider not yet implemented")):
        with caplog.at_level(logging.ERROR, logger="csc.pipeline.scheduler"):
            from csc.pipeline.scheduler import _send_alert
            _send_alert()

    assert any("SendGrid" in r.message for r in caplog.records)
