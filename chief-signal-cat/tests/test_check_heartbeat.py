"""
Tests for csc.tools.check_heartbeat — stale/fresh detection and alert dispatch.
Brief files are created under tmp_path with explicit mtimes; SMTP is mocked.
"""
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from csc.tools.check_heartbeat import EMAIL_YAML as EMAIL_YAML_PATH
from csc.tools.check_heartbeat import _send_smtp, check, format_status, main, read_email_cfg

ROOT = Path(__file__).resolve().parent.parent
SYSTEM_PYTHON = "/usr/bin/python3"

NOW = time.time()
HOUR = 3600


def _touch(path: Path, hours_ago: float) -> Path:
    path.write_text("brief")
    ts = NOW - hours_ago * HOUR
    os.utime(path, (ts, ts))
    return path


@pytest.fixture
def briefs_dir(tmp_path):
    d = tmp_path / "briefs"
    d.mkdir()
    return d


@pytest.fixture
def fresh_briefs(briefs_dir):
    """An old brief plus one from 5h ago — newest is fresh."""
    _touch(briefs_dir / "old.md", hours_ago=100)
    _touch(briefs_dir / "new.md", hours_ago=5)
    return briefs_dir


@pytest.fixture
def stale_briefs(briefs_dir):
    """Newest brief is 40h old; a fresh .gitkeep must not count."""
    _touch(briefs_dir / "a.md", hours_ago=72)
    _touch(briefs_dir / "b.md", hours_ago=40)
    _touch(briefs_dir / ".gitkeep", hours_ago=0)
    return briefs_dir


# ── check ─────────────────────────────────────────────────────

def test_fresh_when_newest_within_threshold(fresh_briefs):
    fresh, newest, age = check(fresh_briefs, 36, now=NOW)
    assert fresh is True
    assert newest.name == "new.md"
    assert age == pytest.approx(5, abs=0.01)


def test_stale_when_newest_older_than_threshold(stale_briefs):
    fresh, newest, age = check(stale_briefs, 36, now=NOW)
    assert fresh is False
    assert newest.name == "b.md"
    assert age == pytest.approx(40, abs=0.01)


def test_stale_when_dir_empty(briefs_dir):
    assert check(briefs_dir, 36, now=NOW) == (False, None, None)


def test_stale_when_dir_missing(tmp_path):
    assert check(tmp_path / "nope", 36, now=NOW) == (False, None, None)


def test_threshold_is_inclusive(briefs_dir):
    _touch(briefs_dir / "edge.md", hours_ago=36)
    fresh, _, _ = check(briefs_dir, 36, now=NOW)
    assert fresh is True


def test_format_status_no_briefs():
    assert format_status(False, None, None, 36) == "STALE: no briefs found (threshold 36h)"


# ── main / alert ──────────────────────────────────────────────

def test_main_fresh_returns_0_and_sends_nothing(fresh_briefs):
    with patch("csc.tools.check_heartbeat.send_alert") as mock_alert:
        rc = main(["--briefs-dir", str(fresh_briefs)])
    assert rc == 0
    mock_alert.assert_not_called()


def test_main_stale_returns_1_and_alerts(stale_briefs):
    with patch("csc.tools.check_heartbeat.send_alert") as mock_alert:
        rc = main(["--briefs-dir", str(stale_briefs)])
    assert rc == 1
    mock_alert.assert_called_once()
    status = mock_alert.call_args.args[0]
    assert status.startswith("STALE") and "b.md" in status


def test_main_no_email_flag_suppresses_alert(stale_briefs):
    with patch("csc.tools.check_heartbeat.send_alert") as mock_alert:
        rc = main(["--briefs-dir", str(stale_briefs), "--no-email"])
    assert rc == 1
    mock_alert.assert_not_called()


EMAIL_YAML = """\
email:
  provider: "smtp"  # or "sendgrid"
  smtp_host: ""
  smtp_port: 587
  from_address: "from@example.com"
  recipients:
    - "someone@example.com"
  alert_address: 'ops@example.com'   # alerts go here
other:
  alert_address: "not-this@example.com"
"""


@pytest.fixture
def email_yaml(tmp_path):
    p = tmp_path / "email.yaml"
    p.write_text(EMAIL_YAML)
    return p


def test_read_email_cfg_scalars_only(email_yaml):
    assert read_email_cfg(email_yaml) == {
        "provider": "smtp",
        "smtp_port": "587",
        "from_address": "from@example.com",
        "alert_address": "ops@example.com",
    }


def test_read_email_cfg_matches_real_config_alert_address():
    """The stdlib reader must agree with PyYAML on the real config file."""
    import yaml
    real = yaml.safe_load(EMAIL_YAML_PATH.read_text())["email"]
    assert read_email_cfg(EMAIL_YAML_PATH)["alert_address"] == real["alert_address"]


def test_send_alert_uses_email_config_alert_address(stale_briefs, email_yaml):
    with patch("csc.tools.check_heartbeat.EMAIL_YAML", email_yaml), \
         patch("csc.tools.check_heartbeat.load_dotenv"), \
         patch("csc.tools.check_heartbeat._send_smtp") as mock_send:
        main(["--briefs-dir", str(stale_briefs)])
    mock_send.assert_called_once()
    subject, body, recipients, cfg = mock_send.call_args.args
    assert recipients == ["ops@example.com"]
    assert cfg["from_address"] == "from@example.com"
    assert "[CSC ALERT]" in subject
    assert "b.md" in body


def test_send_alert_skips_without_alert_address(stale_briefs, tmp_path):
    empty = tmp_path / "empty.yaml"
    empty.write_text("email:\n  provider: smtp\n")
    with patch("csc.tools.check_heartbeat.EMAIL_YAML", empty), \
         patch("csc.tools.check_heartbeat.load_dotenv"), \
         patch("csc.tools.check_heartbeat._send_smtp") as mock_send:
        rc = main(["--briefs-dir", str(stale_briefs)])
    assert rc == 1
    mock_send.assert_not_called()


def test_smtp_message_built_from_env_and_cfg(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "pw")
    with patch("csc.tools.check_heartbeat.smtplib.SMTP") as mock_smtp:
        _send_smtp("subj", "body", ["ops@example.com"], {"from_address": "from@example.com"})
    mock_smtp.assert_called_once_with("smtp.example.com", 2525, timeout=10)
    server = mock_smtp.return_value.__enter__.return_value
    server.login.assert_called_once_with("user", "pw")
    from_addr, to, raw = server.sendmail.call_args.args
    assert (from_addr, to) == ("from@example.com", ["ops@example.com"])
    assert "Subject: subj" in raw


# ── stdlib-only ───────────────────────────────────────────────

def test_imports_are_stdlib_only():
    """Importing the module must pull in no third-party package and no other csc module."""
    code = (
        "import sys; before = set(sys.modules); import csc.tools.check_heartbeat; "
        "new = {m.split('.')[0] for m in set(sys.modules) - before}; "
        "bad = sorted(m for m in new if m not in sys.stdlib_module_names and m != 'csc'); "
        "csc_mods = sorted(m for m in sys.modules if m.startswith('csc')); "
        "print(bad, csc_mods)"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[] ['csc', 'csc.tools', 'csc.tools.check_heartbeat']"


@pytest.mark.skipif(not Path(SYSTEM_PYTHON).exists(), reason="no /usr/bin/python3")
def test_runs_under_system_python(fresh_briefs):
    """launchd runs the heartbeat with /usr/bin/python3 (3.9, no project deps)."""
    out = subprocess.run(
        [SYSTEM_PYTHON, "-m", "csc.tools.check_heartbeat", "--no-email", "--briefs-dir", str(fresh_briefs)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.startswith("OK: newest brief new.md")
