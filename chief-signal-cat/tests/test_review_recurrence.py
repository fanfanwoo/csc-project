"""Tests for the review-queue recurrence watch tool. Clustering is exact-URL."""
from csc.tools.review_recurrence import (
    build_clusters,
    recurring,
    signal_key,
    _held_single_source_items,
)


def _held(title, reason, url, source="ASIC Media", category="official"):
    return {
        "title": title, "human_review_reason": reason,
        "canonical_url": url, "url": url,
        "source_name": source, "evidence_category": category,
    }


def test_signal_key_prefers_canonical_url():
    assert signal_key({"canonical_url": "https://a", "url": "https://b"}) == "https://a"
    assert signal_key({"canonical_url": None, "url": "https://b"}) == "https://b"
    assert signal_key({}) == ""


def test_same_url_across_runs_clusters_as_recurrence():
    runs = {
        "run1": [_held("ASIC reviews car finance", "single_source_high_impact", "https://asic.gov.au/x1")],
        "run2": [_held("ASIC reviews car finance", "single_source_high_impact", "https://asic.gov.au/x1")],
    }
    (cluster,) = recurring(build_clusters(runs), min_runs=2)
    assert cluster.run_count == 2
    assert "single_source_high_impact" in cluster.reasons


def test_evergreen_same_title_different_url_is_not_recurrence():
    # The trap: near-identical headline, DISTINCT events at DISTINCT URLs (e.g. a
    # quarterly CPI print). These must NOT cluster — that would manufacture false
    # recurrence. Event discrimination is the agent's job, not the watch's.
    runs = {
        "q1": [_held("Interest rate hikes back in focus as inflation persists",
                     "single_source_high_impact", "https://brokernews.com.au/a-289570.aspx",
                     "Australian Broker", "publisher")],
        "q2": [_held("Interest rate hikes back in focus as inflation persists",
                     "single_source_high_impact", "https://brokernews.com.au/a-300012.aspx",
                     "Australian Broker", "publisher")],
    }
    clusters = build_clusters(runs)
    assert len(clusters) == 2
    assert recurring(clusters, min_runs=2) == []


def test_one_off_hold_is_not_recurring():
    runs = {"run1": [_held("A one-time item", "single_source_high_impact", "https://x/1")]}
    assert recurring(build_clusters(runs), min_runs=2) == []


def test_sensitive_only_and_retired_reasons_excluded():
    runs = {
        "r1": [_held("Sensitive item", "sensitive_domain", "https://x/1")],
        "r2": [_held("Sensitive item", "sensitive_domain", "https://x/1")],
        "r3": [_held("Old verbose item", "large_inference_leap", "https://x/2")],
    }
    assert build_clusters(runs) == []
    assert recurring(build_clusters(runs), min_runs=2) == []


def test_headline_only_high_impact_is_a_corroboration_reason():
    runs = {
        "r1": [_held("Google headline story", "headline_only_high_impact",
                     "https://news.google.com/rss/articles/CBMiX", "Google News AU", "aggregator")],
        "r2": [_held("Google headline story", "sensitive_domain, headline_only_high_impact",
                     "https://news.google.com/rss/articles/CBMiX", "Google News AU", "aggregator")],
    }
    (cluster,) = recurring(build_clusters(runs), min_runs=2)
    assert cluster.run_count == 2


def test_official_recurrence_is_not_a_corroboration_candidate():
    runs = {
        "r1": [_held("ASIC consumer credit review", "single_source_high_impact",
                     "https://asic.gov.au/ccr", "ASIC Media", "official")],
        "r2": [_held("ASIC consumer credit review", "single_source_high_impact",
                     "https://asic.gov.au/ccr", "ASIC Media", "official")],
    }
    (cluster,) = recurring(build_clusters(runs), min_runs=2)
    assert cluster.run_count == 2
    assert cluster.is_corroboration_candidate is False


def test_non_official_recurrence_is_a_corroboration_candidate():
    runs = {
        "r1": [_held("Lone broker scoop", "single_source_high_impact",
                     "https://brokernews.com.au/scoop.aspx", "Australian Broker", "publisher")],
        "r2": [_held("Lone broker scoop", "single_source_high_impact",
                     "https://brokernews.com.au/scoop.aspx", "Australian Broker", "publisher")],
    }
    (cluster,) = recurring(build_clusters(runs), min_runs=2)
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
