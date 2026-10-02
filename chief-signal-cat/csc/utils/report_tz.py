"""
Shared report timezone — the calendar human-facing dates are rendered in.

Stored timestamps stay UTC (Brief.generated_at, RunLog.started_at, every
persisted field). Only the date *labels* a person reads are converted: the
brief's date_range and the run-metrics date column. A 07:00 Sydney run is
still the previous day in UTC, so labelling from UTC dates every morning
brief and every run as yesterday.

Configured once, top level in config/pipeline.yaml (`timezone:`). Unset or
unknown falls back to UTC, so a missing key degrades to the stored calendar
rather than to a crash.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from csc.utils.logging import get_logger

logger = get_logger(__name__)


def report_tz(cfg: dict) -> ZoneInfo | timezone:
    """Resolve the configured report timezone; UTC when unset or unknown."""
    name = cfg.get("timezone")
    if not name:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("unknown report timezone, using UTC", extra={"timezone": name})
        return timezone.utc


def local_date(ts: datetime, tz: ZoneInfo | timezone) -> str:
    """Render a timestamp's calendar date in tz. Naive input is read as UTC."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(tz).strftime("%Y-%m-%d")
