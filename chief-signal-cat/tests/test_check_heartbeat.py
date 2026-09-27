"""
Tests for csc.tools.check_heartbeat — stale/fresh detection and alert dispatch.
Brief files are created under tmp_path with explicit mtimes; email is mocked.
"""
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from csc.tools.check_heartbeat import check, format_status, main

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


def test_send_alert_uses_email_config_alert_address(stale_briefs):
    cfg = {"email": {"provider": "smtp", "alert_address": "ops@example.com"}}
    with patch("csc.config.load_config", return_value=cfg), \
         patch("csc.pipeline.send_email.send_plain_text") as mock_send:
        main(["--briefs-dir", str(stale_briefs)])
    mock_send.assert_called_once()
    kwargs = mock_send.call_args.kwargs
    assert kwargs["cfg"]["alert_address"] == "ops@example.com"
    assert "[CSC ALERT]" in kwargs["subject"]
    assert "b.md" in kwargs["body"]


def test_send_alert_skips_without_alert_address(stale_briefs):
    with patch("csc.config.load_config", return_value={"email": {}}), \
         patch("csc.pipeline.send_email.send_plain_text") as mock_send:
        rc = main(["--briefs-dir", str(stale_briefs)])
    assert rc == 1
    mock_send.assert_not_called()
