"""
Source-health tests.

The decay this guards against is silent: a frozen or empty feed leaves a brief
that reads exactly like a healthy one. So the cases that matter are the ones
where *nothing* arrives — zero items, undated items, a source absent from the
fetch entirely — and they are asserted on the rendered section a reader sees,
not only on the dataclass.
"""

import logging
from datetime import datetime, timedelta, timezone

import pytest

from csc.connectors.http import validate_source_config
from csc.pipeline.source_health import (
    assess_sources,
    render_source_health,
)
from csc.schemas.items import RawItem

NOW = datetime(2026, 10, 2, 21, 0, tzinfo=timezone.utc)

SOURCES = [
    {
        "name": "ASIC Media", "type": "regulator", "trust_tier": "official",
        "url": "https://example.com/asic.json", "region": "AU", "max_staleness_days": 4,
    },
    {
        "name": "Australian Broker", "type": "news", "trust_tier": "trade_press",
        "url": "https://example.com/ab.rss", "region": "AU", "max_staleness_days": 4,
    },
    {
        "name": "Google News AU", "type": "news", "trust_tier": "aggregator",
        "url": "https://example.com/gn.rss", "region": "AU", "max_staleness_days": 3,
    },
]


def _item(source_name: str, days_old: float | None, n: int = 0) -> RawItem:
    published = None if days_old is None else NOW - timedelta(days=days_old)
    return RawItem(
        id=f"{source_name}-{n}", url=f"https://example.com/{source_name}/{n}",
        canonical_url=None, title=f"Item {n}", body="Body.",
        source_name=source_name, source_type="news", region="AU",
        published_at=published, fetched_at=NOW, raw_metadata={},
    )


def _by_name(report):
    return {h.source_name: h for h in report}


# ── Fresh ─────────────────────────────────────────────────────

def test_fresh_feed_is_ok():
    items = [_item("ASIC Media", 0.5), _item("ASIC Media", 2.0, n=1)]
    health = _by_name(assess_sources(items, [SOURCES[0]], now=NOW))["ASIC Media"]

    assert health.status == "ok"
    assert health.is_warning is False
    assert health.reason == ""
    assert health.item_count == 2
    assert health.newest_item_date == "2026-10-02"   # the newest item, not the oldest
    assert health.age_days == 0.5
    assert health.threshold_days == 4


def test_fresh_feed_renders_its_newest_date_and_ok():
    report = assess_sources([_item("ASIC Media", 0.5)], [SOURCES[0]], now=NOW)
    out = render_source_health(report)

    assert "## Source health" in out
    assert "all sources fresh" in out
    assert "ASIC Media" in out
    assert "newest 2026-10-02" in out
    assert "OK" in out
    assert "WARNING" not in out


def test_item_exactly_at_the_threshold_is_still_ok():
    # The threshold is a limit, not a trigger: 4.0d old against a 4d threshold passes.
    report = assess_sources([_item("ASIC Media", 4.0)], [SOURCES[0]], now=NOW)
    assert _by_name(report)["ASIC Media"].status == "ok"


# ── Stale ─────────────────────────────────────────────────────

def test_stale_feed_warns():
    report = assess_sources([_item("Australian Broker", 7.2)], [SOURCES[1]], now=NOW)
    health = _by_name(report)["Australian Broker"]

    assert health.status == "warning"
    assert health.is_warning is True
    assert health.age_days == 7.2
    assert health.reason == "older than its 4d threshold"


def test_stale_feed_renders_a_warning_that_still_names_the_date():
    report = assess_sources([_item("Australian Broker", 7.2)], [SOURCES[1]], now=NOW)
    out = render_source_health(report)

    assert "1 of 1 source(s) warning" in out
    assert "newest 2026-09-25" in out        # the date is still reported, not hidden
    assert "WARNING: older than its 4d threshold" in out


def test_each_source_is_judged_against_its_own_threshold():
    # 3.5 days old: inside ASIC's 4d allowance, past Google News' 3d one.
    items = [_item("ASIC Media", 3.5), _item("Google News AU", 3.5)]
    report = _by_name(assess_sources(items, [SOURCES[0], SOURCES[2]], now=NOW))

    assert report["ASIC Media"].status == "ok"
    assert report["Google News AU"].status == "warning"


def test_threshold_comes_from_config_not_code():
    # The same feed flips verdict on the config value alone.
    source = dict(SOURCES[1], max_staleness_days=14)
    report = assess_sources([_item("Australian Broker", 7.2)], [source], now=NOW)

    assert _by_name(report)["Australian Broker"].status == "ok"
    assert _by_name(report)["Australian Broker"].threshold_days == 14


# ── Zero items ────────────────────────────────────────────────

def test_zero_items_warns():
    report = assess_sources([], [SOURCES[2]], now=NOW)
    health = _by_name(report)["Google News AU"]

    assert health.status == "warning"
    assert health.item_count == 0
    assert health.newest_item_date == ""
    assert health.age_days is None
    assert health.reason == "returned no items"


def test_zero_items_renders_a_named_warning():
    out = render_source_health(assess_sources([], [SOURCES[2]], now=NOW))

    assert "Google News AU" in out
    assert "no items" in out
    assert "WARNING: returned no items" in out


def test_a_source_absent_from_the_fetch_still_gets_a_line():
    # Other sources delivering must not mask one that returned nothing at all.
    items = [_item("ASIC Media", 0.5)]
    report = _by_name(assess_sources(items, SOURCES, now=NOW))

    assert set(report) == {"ASIC Media", "Australian Broker", "Google News AU"}
    assert report["ASIC Media"].status == "ok"
    assert report["Australian Broker"].status == "warning"
    assert report["Google News AU"].status == "warning"

    out = render_source_health(assess_sources(items, SOURCES, now=NOW))
    assert "2 of 3 source(s) warning" in out


def test_undated_items_warn_because_freshness_is_unprovable():
    report = assess_sources([_item("Google News AU", None)], [SOURCES[2]], now=NOW)
    health = _by_name(report)["Google News AU"]

    assert health.status == "warning"
    assert health.item_count == 1
    assert health.reason == "1 item(s), none carrying a publish date"
    assert "no dated items" in render_source_health(report)


# ── Logging and ordering ──────────────────────────────────────

def test_every_warning_is_logged_at_error(caplog):
    with caplog.at_level(logging.ERROR, logger="csc.pipeline.source_health"):
        assess_sources([_item("ASIC Media", 0.5)], SOURCES, now=NOW)

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 2                                  # the two silent sources
    assert {r.source for r in errors} == {"Australian Broker", "Google News AU"}
    assert all(r.message == "source health warning" for r in errors)


def test_a_healthy_source_logs_no_error(caplog):
    with caplog.at_level(logging.ERROR, logger="csc.pipeline.source_health"):
        assess_sources([_item("ASIC Media", 0.5)], [SOURCES[0]], now=NOW)

    assert [r for r in caplog.records if r.levelno == logging.ERROR] == []


def test_report_follows_config_order():
    report = assess_sources([], SOURCES, now=NOW)
    assert [h.source_name for h in report] == [s["name"] for s in SOURCES]


def test_missing_threshold_leaves_staleness_unchecked_but_says_so(caplog):
    source = {k: v for k, v in SOURCES[1].items() if k != "max_staleness_days"}
    with caplog.at_level(logging.WARNING, logger="csc.pipeline.source_health"):
        report = assess_sources([_item("Australian Broker", 99.0)], [source], now=NOW)

    health = _by_name(report)["Australian Broker"]
    assert health.status == "ok"              # unjudgeable, not silently failed
    assert health.threshold_days is None
    assert any("staleness unchecked" in r.message for r in caplog.records)


# ── Timestamps and timezone ───────────────────────────────────

def test_naive_publish_dates_are_read_as_utc():
    item = _item("ASIC Media", 0.5)
    item.published_at = item.published_at.replace(tzinfo=None)
    report = assess_sources([item], [SOURCES[0]], now=NOW)

    assert _by_name(report)["ASIC Media"].age_days == 0.5


def test_tz_changes_the_date_label_not_the_verdict():
    from zoneinfo import ZoneInfo

    # 2026-10-02 21:00Z is already 2026-10-03 in Sydney.
    report = assess_sources(
        [_item("ASIC Media", 0.0)], [SOURCES[0]], tz=ZoneInfo("Australia/Sydney"), now=NOW
    )
    health = _by_name(report)["ASIC Media"]

    assert health.newest_item_date == "2026-10-03"
    assert health.age_days == 0.0
    assert health.status == "ok"


# ── Config validation ─────────────────────────────────────────

@pytest.mark.parametrize("bad", [0, -1, 4.5, "4", True, None])
def test_invalid_threshold_is_a_fatal_config_error(bad):
    source = dict(SOURCES[0], max_staleness_days=bad)
    with pytest.raises(ValueError, match="max_staleness_days"):
        validate_source_config(source)


def test_threshold_is_optional_in_config():
    source = {k: v for k, v in SOURCES[0].items() if k != "max_staleness_days"}
    validate_source_config(source)   # must not raise


# ── Wiring: the configured timezone reaches the rendered date ──

def test_run_pipeline_passes_the_configured_timezone_to_source_health():
    """The config key, not UTC, decides the newest-item dates a reader sees.

    Asserted on run_pipeline rather than on assess_sources alone: the bug this
    guards against is a forgotten argument in the wiring, which a unit test of
    assess_sources cannot see.
    """
    from datetime import datetime as dt
    from unittest.mock import MagicMock, patch
    from zoneinfo import ZoneInfo

    from csc.config import load_config
    from csc.run import run_pipeline
    from csc.schemas.briefs import Brief

    configured = load_config().get("timezone")
    assert configured, "config/pipeline.yaml has no timezone: key to wire"

    brief = Brief(
        run_id="", date_range="2026-10-02", generated_at=dt.now(timezone.utc),
        one_line_readout="readout", markdown_body="# body",
    )
    with (
        patch("csc.run.fetch_all_sources", return_value=[]),
        patch("csc.run.assess_sources", return_value=[]) as mock_assess,
        patch("csc.run.summarise", return_value=brief),
        patch("csc.run.send_email"),
    ):
        run_pipeline()

    assert mock_assess.call_args.kwargs["tz"] == ZoneInfo(configured)


def test_the_live_config_renders_sydney_dates_not_utc():
    """End to end over the real config: 21:00Z is already tomorrow in Sydney."""
    from csc.config import load_config
    from csc.utils.report_tz import report_tz

    source = dict(SOURCES[0], name="ASIC Media")
    report = assess_sources(
        [_item("ASIC Media", 0.0)], [source], tz=report_tz(load_config()), now=NOW
    )

    # NOW is 2026-10-02 21:00Z — the same instant is 2026-10-03 in Sydney.
    assert _by_name(report)["ASIC Media"].newest_item_date == "2026-10-03"
