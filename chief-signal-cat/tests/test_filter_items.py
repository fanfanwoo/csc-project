"""
Tests for filter_items pipeline stage.
No network calls — pure deterministic logic.
"""

from datetime import datetime, timedelta, timezone

import pytest

from csc.pipeline.filter_items import filter_items
from csc.schemas.items import RawItem

NOW = datetime.now(timezone.utc)

BASE_CFG = {
    "target_regions": ["AU"],
    "max_age_days": 7,
    "domain_allowlist": [],
    "keyword_blocklist": ["advertorial", "sponsored content"],
    "keyword_allowlist": ["ASIC", "car loan", "responsible lending"],
    "require_keyword_match": False,
    "min_keyword_matches": 1,
    "keyword_match_exempt_tiers": [],
    "missing_published_at_policy": {},
}

STRICT_CFG = {
    **BASE_CFG,
    "require_keyword_match": True,
    "keyword_match_exempt_tiers": ["official"],
}

MISSING_DATE_CFG = {
    **BASE_CFG,
    "missing_published_at_policy": {
        "official": "keep_with_warning",
        "regulator": "keep_with_warning",
        "news": "drop",
        "aggregator": "drop",
    },
}


def _item(**kwargs) -> RawItem:
    defaults = dict(
        id="abc123",
        url="https://asic.gov.au/news/1",
        canonical_url="https://asic.gov.au/news/1",
        title="ASIC tightens car loan rules",
        body="Responsible lending update from regulator.",
        source_name="ASIC Media",
        source_type="regulator",
        trust_tier="official",
        source_weight=1.0,
        region="AU",
        published_at=NOW - timedelta(days=1),
        fetched_at=NOW,
        raw_metadata={},
    )
    defaults.update(kwargs)
    return RawItem(**defaults)


# ── Return type and filter_status ─────────────────────────────

def test_returns_all_items_including_dropped():
    items = [_item(), _item(region="US")]
    result = filter_items(items, BASE_CFG)
    assert len(result) == 2


def test_kept_item_has_status_kept_and_no_reason():
    result = filter_items([_item()], BASE_CFG)
    assert result[0].filter_status == "kept"
    assert result[0].filter_reason is None


def test_dropped_item_has_status_dropped_and_reason_string():
    result = filter_items([_item(region="US")], BASE_CFG)
    assert result[0].filter_status == "dropped"
    assert isinstance(result[0].filter_reason, str)


def test_keep_with_warning_has_explicit_status_and_reason():
    item = _item(published_at=None, trust_tier="official", source_type="regulator")
    result = filter_items([item], MISSING_DATE_CFG)
    assert result[0].filter_status == "keep_with_warning"
    assert result[0].filter_reason == "missing_published_at"


# ── Step 1: Region ────────────────────────────────────────────

def test_drops_off_region():
    result = filter_items([_item(region="US")], BASE_CFG)
    assert result[0].filter_status == "dropped"
    assert result[0].filter_reason == "off_region"


def test_keeps_matching_region():
    result = filter_items([_item(region="AU")], BASE_CFG)
    assert result[0].filter_status == "kept"


def test_multi_region_config_keeps_both():
    cfg = {**BASE_CFG, "target_regions": ["AU", "US"]}
    au = _item(region="AU")
    us = _item(region="US", id="us1", url="https://example.com/us")
    result = filter_items([au, us], cfg)
    assert all(i.filter_status == "kept" for i in result)


# ── Step 2: Recency ───────────────────────────────────────────

def test_drops_stale_item():
    result = filter_items([_item(published_at=NOW - timedelta(days=10))], BASE_CFG)
    assert result[0].filter_status == "dropped"
    assert result[0].filter_reason == "stale"


def test_keeps_item_within_max_age():
    result = filter_items([_item(published_at=NOW - timedelta(days=6))], BASE_CFG)
    assert result[0].filter_status == "kept"


def test_drops_item_one_day_past_boundary():
    result = filter_items([_item(published_at=NOW - timedelta(days=8))], BASE_CFG)
    assert result[0].filter_reason == "stale"


# ── Step 2: Missing date — default policy ─────────────────────

def test_missing_date_default_policy_drops():
    result = filter_items([_item(published_at=None)], BASE_CFG)
    assert result[0].filter_status == "dropped"
    assert result[0].filter_reason == "missing_date"


# ── Step 2: Missing date — explicit policy by trust_tier ─────

def test_missing_date_official_keep_with_warning():
    item = _item(published_at=None, trust_tier="official", source_type="regulator")
    result = filter_items([item], MISSING_DATE_CFG)
    assert result[0].filter_status == "keep_with_warning"
    assert result[0].filter_reason == "missing_published_at"


def test_missing_date_news_dropped():
    item = _item(
        published_at=None,
        trust_tier="major_news",
        source_type="news",
        url="https://news.com/1",
        id="n1",
    )
    result = filter_items([item], MISSING_DATE_CFG)
    assert result[0].filter_status == "dropped"
    assert result[0].filter_reason == "missing_date"


def test_missing_date_aggregator_dropped():
    item = _item(
        published_at=None,
        trust_tier="aggregator",
        source_type="news",
        url="https://news.google.com/1",
        id="agg1",
    )
    result = filter_items([item], MISSING_DATE_CFG)
    assert result[0].filter_status == "dropped"


def test_missing_date_keep_with_warning_not_stale():
    # No published_at but policy allows keep — must not be stale
    item = _item(published_at=None, trust_tier="official", source_type="regulator")
    result = filter_items([item], MISSING_DATE_CFG)
    assert result[0].filter_reason != "stale"


# ── Step 3: Domain allowlist ──────────────────────────────────

def test_no_allowlist_allows_all_domains():
    result = filter_items([_item()], {**BASE_CFG, "domain_allowlist": []})
    assert result[0].filter_status == "kept"


def test_domain_allowlist_blocks_unlisted_domain():
    cfg = {**BASE_CFG, "domain_allowlist": ["asic.gov.au"]}
    item = _item(url="https://someothernews.com/article")
    result = filter_items([item], cfg)
    assert result[0].filter_status == "dropped"
    assert result[0].filter_reason == "blocked_domain"


def test_domain_allowlist_keeps_listed_domain():
    cfg = {**BASE_CFG, "domain_allowlist": ["asic.gov.au"]}
    result = filter_items([_item(url="https://asic.gov.au/news/1")], cfg)
    assert result[0].filter_status == "kept"


# ── Step 4: Keyword blocklist ─────────────────────────────────

def test_drops_blocked_keyword_in_title():
    result = filter_items([_item(title="Best car loan advertorial 2026")], BASE_CFG)
    assert result[0].filter_status == "dropped"
    assert result[0].filter_reason == "blocked_keyword"


def test_drops_blocked_keyword_in_body():
    result = filter_items([_item(body="This is sponsored content for car loans.")], BASE_CFG)
    assert result[0].filter_reason == "blocked_keyword"


def test_excluded_keywords_populated_on_blocked_item():
    result = filter_items([_item(title="advertorial car loan")], BASE_CFG)
    assert "advertorial" in result[0].excluded_keywords


def test_excluded_keywords_empty_when_not_blocked():
    result = filter_items([_item()], BASE_CFG)
    assert result[0].excluded_keywords == []


def test_blocklist_case_insensitive():
    result = filter_items([_item(title="ADVERTORIAL post here")], BASE_CFG)
    assert result[0].filter_reason == "blocked_keyword"


# ── Step 5: Keyword allowlist — strict mode ───────────────────

def test_strict_mode_drops_no_keyword_match():
    item = _item(
        trust_tier="major_news",
        source_type="news",
        title="General finance news",
        body="Nothing relevant here.",
        url="https://afr.com/x",
        id="n1",
    )
    result = filter_items([item], STRICT_CFG)
    assert result[0].filter_status == "dropped"
    assert result[0].filter_reason == "no_keyword_match"


def test_strict_mode_keeps_with_keyword_match():
    result = filter_items([_item()], STRICT_CFG)  # title has "ASIC" and "car loan"
    assert result[0].filter_status == "kept"


def test_strict_mode_exempt_tier_kept_without_keyword():
    item = _item(
        trust_tier="official",
        title="Annual report on financial stability",
        body="No keywords here.",
    )
    result = filter_items([item], STRICT_CFG)
    assert result[0].filter_status == "kept"


def test_strict_mode_non_exempt_tier_dropped_without_keyword():
    item = _item(
        trust_tier="aggregator",
        source_type="news",
        title="General news story",
        body="Nothing relevant here at all.",
        url="https://news.google.com/2",
        id="agg2",
    )
    result = filter_items([item], STRICT_CFG)
    assert result[0].filter_status == "dropped"
    assert result[0].filter_reason == "no_keyword_match"


def test_strict_mode_disabled_keeps_without_keyword():
    item = _item(title="General finance news", body="Nothing relevant here.")
    result = filter_items([item], BASE_CFG)  # require_keyword_match=False
    assert result[0].filter_status == "kept"


def test_min_keyword_matches_two_requires_two():
    cfg = {**STRICT_CFG, "min_keyword_matches": 2, "keyword_match_exempt_tiers": []}
    item_one = _item(title="ASIC update", body="Nothing else.")
    item_two = _item(title="ASIC car loan update", body="Responsible lending.", id="b2", url="https://x.com/2")
    results = filter_items([item_one, item_two], cfg)
    assert results[0].filter_reason == "no_keyword_match"
    assert results[1].filter_status == "kept"


# ── matched_keywords ──────────────────────────────────────────

def test_matched_keywords_populated_with_original_case():
    result = filter_items([_item()], BASE_CFG)
    assert "ASIC" in result[0].matched_keywords
    assert "car loan" in result[0].matched_keywords


def test_matched_keywords_empty_when_none_match():
    item = _item(title="General finance news", body="Nothing here.")
    result = filter_items([item], BASE_CFG)
    assert result[0].matched_keywords == []


def test_matched_keywords_case_insensitive_match():
    item = _item(title="asic car loan ruling")
    result = filter_items([item], BASE_CFG)
    assert "ASIC" in result[0].matched_keywords


# ── Filter order ──────────────────────────────────────────────

def test_region_checked_before_recency():
    item = _item(region="US", published_at=NOW - timedelta(days=30))
    result = filter_items([item], BASE_CFG)
    assert result[0].filter_reason == "off_region"


def test_recency_checked_before_domain():
    cfg = {**BASE_CFG, "domain_allowlist": ["asic.gov.au"]}
    item = _item(published_at=NOW - timedelta(days=10), url="https://other.com/x")
    result = filter_items([item], cfg)
    assert result[0].filter_reason == "stale"


def test_domain_checked_before_blocklist():
    cfg = {**BASE_CFG, "domain_allowlist": ["asic.gov.au"]}
    item = _item(url="https://bad.com/advertorial", title="advertorial junk")
    result = filter_items([item], cfg)
    assert result[0].filter_reason == "blocked_domain"


# ── Word boundary matching ────────────────────────────────────

def test_ev_does_not_match_revenue():
    cfg = {**BASE_CFG, "keyword_allowlist": ["EV"], "require_keyword_match": True, "keyword_match_exempt_tiers": []}
    item = _item(
        trust_tier="major_news",
        source_type="news",
        title="Strong revenue growth in auto sector",
        body="Revenue up 12% driven by fleet sales.",
        url="https://afr.com/ev-test",
        id="ev1",
    )
    result = filter_items([item], cfg)
    assert result[0].matched_keywords == []


def test_ev_does_not_match_event():
    cfg = {**BASE_CFG, "keyword_allowlist": ["EV"], "require_keyword_match": True, "keyword_match_exempt_tiers": []}
    item = _item(
        trust_tier="major_news",
        source_type="news",
        title="Industry event on auto lending",
        body="The event covered evolving credit standards.",
        url="https://afr.com/ev-test2",
        id="ev2",
    )
    result = filter_items([item], cfg)
    assert result[0].matched_keywords == []


def test_ev_matches_standalone():
    cfg = {**BASE_CFG, "keyword_allowlist": ["EV"], "require_keyword_match": True, "keyword_match_exempt_tiers": []}
    item = _item(
        trust_tier="major_news",
        source_type="news",
        title="EV sales surge in Q1 2026",
        body="Electric vehicle demand up 40%.",
        url="https://afr.com/ev-test3",
        id="ev3",
    )
    result = filter_items([item], cfg)
    assert "EV" in result[0].matched_keywords


def test_blocklist_word_boundary_no_false_positive():
    item = _item(title="How lenders inadvertently trap borrowers", body="No junk here.")
    result = filter_items([item], BASE_CFG)
    assert result[0].filter_reason != "blocked_keyword"


# ── keep_with_warning continues through remaining checks ──────

def test_keep_with_warning_dropped_by_blocked_domain():
    cfg = {**MISSING_DATE_CFG, "domain_allowlist": ["asic.gov.au"]}
    item = _item(
        published_at=None,
        trust_tier="official",
        source_type="regulator",
        url="https://otherdomain.com/article",
    )
    result = filter_items([item], cfg)
    assert result[0].filter_status == "dropped"
    assert result[0].filter_reason == "blocked_domain"


def test_keep_with_warning_dropped_by_blocked_keyword():
    item = _item(
        published_at=None,
        trust_tier="official",
        source_type="regulator",
        title="advertorial financial update",
    )
    result = filter_items([item], MISSING_DATE_CFG)
    assert result[0].filter_status == "dropped"
    assert result[0].filter_reason == "blocked_keyword"


def test_keep_with_warning_clean_item_passes():
    item = _item(published_at=None, trust_tier="official", source_type="regulator")
    result = filter_items([item], MISSING_DATE_CFG)
    assert result[0].filter_status == "keep_with_warning"


# ── Recency boundary — timedelta precision ────────────────────

def test_recency_uses_timedelta_not_days_floor():
    # 7 days and 1 second old — should be dropped (was kept under .days floor)
    just_over = NOW - timedelta(days=7, seconds=1)
    result = filter_items([_item(published_at=just_over)], BASE_CFG)
    assert result[0].filter_status == "dropped"
    assert result[0].filter_reason == "stale"


def test_recency_just_under_boundary_kept():
    just_under = NOW - timedelta(days=7) + timedelta(seconds=10)
    result = filter_items([_item(published_at=just_under)], BASE_CFG)
    assert result[0].filter_status == "kept"


# ── Domain normalisation ──────────────────────────────────────

def test_www_prefix_normalised_in_url():
    cfg = {**BASE_CFG, "domain_allowlist": ["asic.gov.au"]}
    item = _item(url="https://www.asic.gov.au/news/1")
    result = filter_items([item], cfg)
    assert result[0].filter_status == "kept"


def test_www_prefix_normalised_in_config():
    cfg = {**BASE_CFG, "domain_allowlist": ["www.asic.gov.au"]}
    item = _item(url="https://asic.gov.au/news/1")
    result = filter_items([item], cfg)
    assert result[0].filter_status == "kept"


def test_domain_case_normalised():
    cfg = {**BASE_CFG, "domain_allowlist": ["ASIC.GOV.AU"]}
    item = _item(url="https://asic.gov.au/news/1")
    result = filter_items([item], cfg)
    assert result[0].filter_status == "kept"


# ── Edge cases ────────────────────────────────────────────────

def test_empty_input_returns_empty():
    result = filter_items([], BASE_CFG)
    assert result == []


def test_mixed_statuses():
    items = [
        _item(),
        _item(region="US", id="b", url="https://example.com/b"),
        _item(title="advertorial junk", id="c", url="https://example.com/c"),
    ]
    result = filter_items(items, BASE_CFG)
    kept = [i for i in result if i.filter_status == "kept"]
    dropped = [i for i in result if i.filter_status == "dropped"]
    assert len(kept) == 1
    assert len(dropped) == 2
