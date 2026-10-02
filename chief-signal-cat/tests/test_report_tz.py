"""
Report-timezone tests.

The regression these lock down: a 07:00 Sydney run is 20:00/21:00 the previous
day in UTC, so a UTC-derived date label calls every morning brief and every run
"yesterday". Both offsets are covered because Sydney moves: AEST is UTC+10,
AEDT is UTC+11.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from csc.tools.run_metrics_report import _date_cell, format_report
from csc.utils.report_tz import local_date, report_tz

SYDNEY = ZoneInfo("Australia/Sydney")

# 07:00 Sydney, expressed in UTC, on each side of the DST boundary.
AEST_0700_UTC = datetime(2026, 7, 2, 21, 0, tzinfo=timezone.utc)   # UTC+10 → 2026-07-03
AEDT_0700_UTC = datetime(2026, 10, 1, 20, 0, tzinfo=timezone.utc)  # UTC+11 → 2026-10-02


def test_report_tz_resolves_configured_zone():
    assert report_tz({"timezone": "Australia/Sydney"}) == SYDNEY


def test_report_tz_falls_back_to_utc_when_unset():
    assert report_tz({}) is timezone.utc
    assert report_tz({"timezone": ""}) is timezone.utc


def test_report_tz_falls_back_to_utc_when_unknown():
    assert report_tz({"timezone": "Mars/Olympus_Mons"}) is timezone.utc


def test_local_date_labels_the_sydney_day_in_aest():
    assert AEST_0700_UTC.strftime("%Y-%m-%d") == "2026-07-02"  # the UTC label, one day behind
    assert local_date(AEST_0700_UTC, SYDNEY) == "2026-07-03"


def test_local_date_labels_the_sydney_day_in_aedt():
    assert AEDT_0700_UTC.strftime("%Y-%m-%d") == "2026-10-01"  # the UTC label, one day behind
    assert local_date(AEDT_0700_UTC, SYDNEY) == "2026-10-02"


def test_local_date_reads_naive_timestamps_as_utc():
    # RunLog.started_at is persisted naive; it is UTC, not local wall time.
    assert local_date(AEDT_0700_UTC.replace(tzinfo=None), SYDNEY) == "2026-10-02"


def test_local_date_in_utc_is_the_stored_date():
    assert local_date(AEDT_0700_UTC, timezone.utc) == "2026-10-01"


def _run(started_at: str) -> dict:
    return {"run_id": "abcd1234-ef", "started_at": started_at, "metrics": {"enrich_success": 3}}


def test_metrics_date_cell_renders_the_local_day():
    assert _date_cell("2026-10-01T21:31:39.961578", SYDNEY) == "2026-10-02"
    assert _date_cell("2026-07-02T21:00:00", SYDNEY) == "2026-07-03"


def test_metrics_date_cell_tolerates_unparseable_and_empty_values():
    assert _date_cell("not-a-timestamp", SYDNEY) == "not-a-time"
    assert _date_cell("", SYDNEY) == ""


def test_metrics_report_shows_the_local_date_column():
    out = format_report([_run("2026-10-01T21:31:39.961578")], limit=5, tz=SYDNEY)
    assert "2026-10-02" in out
    assert "2026-10-01" not in out


def test_metrics_report_defaults_to_utc():
    out = format_report([_run("2026-10-01T21:31:39.961578")], limit=5)
    assert "2026-10-01" in out
