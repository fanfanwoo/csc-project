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

    def side_effect(**kwargs):
        r = results.pop(0)
        if isinstance(r, Exception):
            raise r

    with patch("csc.pipeline.scheduler.run_pipeline", side_effect=side_effect) as mock_run, \
         patch("csc.pipeline.scheduler._send_alert") as mock_alert:
        from csc.pipeline.scheduler import run_once
        run_once()

    assert mock_run.call_args_list == [
        call(trigger="scheduled", attempt=1),
        call(trigger="scheduled", attempt=2),
    ]
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


# ── Config errors reach the alert ─────────────────────────────

def _write_configs(cfg_dir, sources_yaml: str) -> None:
    """A minimal three-file config tree; only sources.yaml varies per test."""
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "sources.yaml").write_text(sources_yaml)
    (cfg_dir / "pipeline.yaml").write_text("pipeline:\n  synthesis_window_days: 3\n")
    (cfg_dir / "email.yaml").write_text(
        'email:\n  provider: "smtp"\n  from_address: "csc@example.com"\n'
        '  recipients:\n    - "reader@example.com"\n  alert_address: "alert@example.com"\n'
    )


_VALID_SOURCE = '''sources:
  - name: "ASIC Media"
    type: "regulator"
    trust_tier: "official"
    url: "https://example.com/asic.json"
    region: "AU"
    max_staleness_days: 4
'''

# The typo under test: max_staleness_days must be a positive integer.
_TYPO_SOURCE = _VALID_SOURCE.replace("max_staleness_days: 4", 'max_staleness_days: "4 days"')


def test_a_config_typo_still_sends_the_failure_alert(tmp_path, monkeypatch):
    """A fatal config error aborts before any fetch — the alert must still fire.

    validate_source_config raises inside fetch_all_sources, which is inside
    run_pipeline's try, so the error propagates to run_once, exhausts both
    attempts, and reaches _send_alert. No network is touched: validation runs
    before the first request.
    """
    cfg_dir = tmp_path / "config"
    _write_configs(cfg_dir, _TYPO_SOURCE)
    monkeypatch.setattr("csc.config._CONFIG_DIR", cfg_dir)

    with (
        patch("csc.pipeline.send_email._send_smtp") as mock_smtp,
        pytest.raises(SystemExit) as exit_info,
    ):
        from csc.pipeline.scheduler import run_once
        run_once()

    assert exit_info.value.code == 1
    mock_smtp.assert_called_once()
    subject, body, recipients, _cfg = mock_smtp.call_args.args
    assert recipients == ["alert@example.com"]
    assert subject == "[CSC ALERT] Pipeline failed after 2 attempts"


def test_the_config_error_is_logged_before_the_alert(tmp_path, monkeypatch, caplog):
    """The alert says only 'failed'; the reason has to be findable in the log."""
    cfg_dir = tmp_path / "config"
    _write_configs(cfg_dir, _TYPO_SOURCE)
    monkeypatch.setattr("csc.config._CONFIG_DIR", cfg_dir)

    with (
        caplog.at_level(logging.ERROR),
        patch("csc.pipeline.send_email._send_smtp"),
        pytest.raises(SystemExit),
    ):
        from csc.pipeline.scheduler import run_once
        run_once()

    assert any("max_staleness_days" in str(r.__dict__.get("error", "")) for r in caplog.records)


def test_unparseable_config_cannot_alert_and_only_logs(tmp_path, monkeypatch, caplog):
    """The one gap: _send_alert needs load_config for the address.

    A value typo is caught after the config loads, so the alert address is
    available. Broken YAML *syntax* breaks load_config itself, inside
    _send_alert's own try — so no email can be sent and the failure survives
    only in the log. Documenting it here rather than claiming alerts are
    unconditional.
    """
    cfg_dir = tmp_path / "config"
    _write_configs(cfg_dir, "sources:\n  - name: [unclosed\n")
    monkeypatch.setattr("csc.config._CONFIG_DIR", cfg_dir)

    with (
        caplog.at_level(logging.ERROR),
        patch("csc.pipeline.send_email._send_smtp") as mock_smtp,
        pytest.raises(SystemExit),
    ):
        from csc.pipeline.scheduler import run_once
        run_once()

    mock_smtp.assert_not_called()
    assert any("failed to send alert email" in r.message for r in caplog.records)
