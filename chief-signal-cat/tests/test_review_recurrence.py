"""Tests for the review-queue recurrence watch tool. Clustering is exact-URL;
recurrence is counted in distinct calendar days."""
from datetime import timedelta, timezone

from csc.tools.review_recurrence import (
    build_clusters,
    format_report,
    held_day,
    recurring,
    signal_key,
    _held_single_source_items,
)

UTC = timezone.utc


def _held(title, reason, url, source="ASIC Media", category="official", fetched_at=None):
    return {
        "title": title, "human_review_reason": reason,
        "canonical_url": url, "url": url,
        "source_name": source, "evidence_category": category,
        "fetched_at": fetched_at,
    }


def _day(n):
    """fetched_at on 2026-06-0n at noon UTC."""
    return f"2026-06-0{n}T12:00:00+00:00"


def test_signal_key_prefers_canonical_url():
    assert signal_key({"canonical_url": "https://a", "url": "https://b"}) == "https://a"
    assert signal_key({"canonical_url": None, "url": "https://b"}) == "https://b"
    assert signal_key({}) == ""


def test_same_url_across_runs_clusters_as_recurrence():
    runs = {
        "run1": [_held("ASIC reviews car finance", "single_source_high_impact", "https://asic.gov.au/x1", fetched_at=_day(1))],
        "run2": [_held("ASIC reviews car finance", "single_source_high_impact", "https://asic.gov.au/x1", fetched_at=_day(2))],
    }
    (cluster,) = recurring(build_clusters(runs), min_days=2)
    assert cluster.run_count == 2
    assert "single_source_high_impact" in cluster.reasons


def test_evergreen_same_title_different_url_is_not_recurrence():
    # The trap: near-identical headline, DISTINCT events at DISTINCT URLs (e.g. a
    # quarterly CPI print). These must NOT cluster — that would manufacture false
    # recurrence. Event discrimination is the agent's job, not the watch's.
    runs = {
        "q1": [_held("Interest rate hikes back in focus as inflation persists",
                     "single_source_high_impact", "https://brokernews.com.au/a-289570.aspx",
                     "Australian Broker", "publisher", fetched_at=_day(3))],
        "q2": [_held("Interest rate hikes back in focus as inflation persists",
                     "single_source_high_impact", "https://brokernews.com.au/a-300012.aspx",
                     "Australian Broker", "publisher", fetched_at=_day(1))],
    }
    clusters = build_clusters(runs)
    assert len(clusters) == 2
    assert recurring(clusters, min_days=2) == []


def test_one_off_hold_is_not_recurring():
    runs = {"run1": [_held("A one-time item", "single_source_high_impact", "https://x/1")]}
    assert recurring(build_clusters(runs), min_days=2) == []


def test_sensitive_only_and_retired_reasons_excluded():
    runs = {
        "r1": [_held("Sensitive item", "sensitive_domain", "https://x/1", fetched_at=_day(2))],
        "r2": [_held("Sensitive item", "sensitive_domain", "https://x/1", fetched_at=_day(3))],
        "r3": [_held("Old verbose item", "large_inference_leap", "https://x/2", fetched_at=_day(1))],
    }
    assert build_clusters(runs) == []
    assert recurring(build_clusters(runs), min_days=2) == []


def test_headline_only_high_impact_is_a_corroboration_reason():
    runs = {
        "r1": [_held("Google headline story", "headline_only_high_impact",
                     "https://news.google.com/rss/articles/CBMiX", "Google News AU", "aggregator", fetched_at=_day(2))],
        "r2": [_held("Google headline story", "sensitive_domain, headline_only_high_impact",
                     "https://news.google.com/rss/articles/CBMiX", "Google News AU", "aggregator", fetched_at=_day(3))],
    }
    (cluster,) = recurring(build_clusters(runs), min_days=2)
    assert cluster.run_count == 2


def test_official_recurrence_is_not_a_corroboration_candidate():
    runs = {
        "r1": [_held("ASIC consumer credit review", "single_source_high_impact",
                     "https://asic.gov.au/ccr", "ASIC Media", "official", fetched_at=_day(2))],
        "r2": [_held("ASIC consumer credit review", "single_source_high_impact",
                     "https://asic.gov.au/ccr", "ASIC Media", "official", fetched_at=_day(3))],
    }
    (cluster,) = recurring(build_clusters(runs), min_days=2)
    assert cluster.run_count == 2
    assert cluster.is_corroboration_candidate is False


def test_non_official_recurrence_is_a_corroboration_candidate():
    runs = {
        "r1": [_held("Lone broker scoop", "single_source_high_impact",
                     "https://brokernews.com.au/scoop.aspx", "Australian Broker", "publisher", fetched_at=_day(2))],
        "r2": [_held("Lone broker scoop", "single_source_high_impact",
                     "https://brokernews.com.au/scoop.aspx", "Australian Broker", "publisher", fetched_at=_day(3))],
    }
    (cluster,) = recurring(build_clusters(runs), min_days=2)
    assert cluster.is_corroboration_candidate is True


def test_held_single_source_items_filters_file(tmp_path):
    import json
    p = tmp_path / "run.jsonl"
    p.write_text(
        json.dumps(_held("kept", "single_source_high_impact", "https://x/1")) + "\n"
        + json.dumps(_held("dropped", "sensitive_domain", "https://x/2")) + "\n"
    )
    items = _held_single_source_items(str(p))
    assert len(items) == 1
    assert items[0]["title"] == "kept"


# ── distinct calendar days ────────────────────────────────────

def test_same_day_reruns_count_one_day_not_recurring():
    # Two runs on one day (e.g. a manual re-run) re-hold the same article: 2 runs, 1 day.
    runs = {
        "am": [_held("Scoop", "single_source_high_impact", "https://x/s", "Australian Broker", "publisher",
                     fetched_at="2026-06-01T08:00:00+00:00")],
        "pm": [_held("Scoop", "single_source_high_impact", "https://x/s", "Australian Broker", "publisher",
                     fetched_at="2026-06-01T20:00:00+00:00")],
    }
    (cluster,) = build_clusters(runs, tz=UTC)
    assert (cluster.run_count, cluster.day_count) == (2, 1)
    assert recurring([cluster], min_days=2) == []


def test_day_uses_given_timezone():
    # 21:00Z on the 1st is already the 2nd in UTC+10 (the 07:00 local schedule).
    item = {"fetched_at": "2026-06-01T21:00:00+00:00"}
    assert held_day(item, tz=UTC) == "2026-06-01"
    assert held_day(item, tz=timezone(timedelta(hours=10))) == "2026-06-02"


def test_missing_or_bad_fetched_at_has_no_day():
    assert held_day({}) is None
    assert held_day({"fetched_at": "not a date"}) is None


def test_report_shows_days_and_runs():
    runs = {
        f"r{n}": [_held("Scoop", "single_source_high_impact", "https://x/s", "Australian Broker", "publisher",
                        fetched_at=_day(d))]
        for n, d in [(1, 1), (2, 1), (3, 2)]
    }
    report = format_report(runs, build_clusters(runs, tz=UTC), min_days=2)
    assert "[2 days / 3 runs] 'Scoop'" in report
    assert "days=2026-06-01..2026-06-02" in report
    assert "recurring on >= 2 distinct days: 1" in report
