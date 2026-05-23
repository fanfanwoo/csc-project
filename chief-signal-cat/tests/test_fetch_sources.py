"""
Tests for source connector.
All tests run without network access — HTTP is mocked.
"""

import urllib.error
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from csc.connectors.rss_connector import (
    _parse_date,
    _parse_rss,
    _strip_html,
    fetch_all_sources,
    fetch_rss,
    validate_source_config,
)
from csc.schemas.items import RawItem

# ── Fixtures ──────────────────────────────────────────────────

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>car loan OR vehicle finance - Google News</title>
    <link>https://news.google.com</link>
    <item>
      <title>ASIC cracks down on car loan brokers over irresponsible lending</title>
      <link>https://www.afr.com/policy/asic-car-loan-crackdown-20260518</link>
      <description>&lt;p&gt;ASIC launched enforcement action against three car loan brokers for failing responsible lending obligations.&lt;/p&gt;</description>
      <pubDate>Mon, 18 May 2026 08:30:00 GMT</pubDate>
      <source url="https://www.afr.com">Australian Financial Review</source>
    </item>
    <item>
      <title>EV sales surge as BNPL enters auto finance</title>
      <link>https://www.abc.net.au/news/ev-bnpl-auto-finance-2026</link>
      <description>&lt;a href="https://www.abc.net.au"&gt;ABC News&lt;/a&gt; — BNPL providers entering car finance market.</description>
      <pubDate>Sun, 17 May 2026 14:00:00 GMT</pubDate>
      <source url="https://www.abc.net.au">ABC News</source>
    </item>
    <item>
      <title>Item with no date</title>
      <link>https://www.example.com/no-date-article</link>
      <description>This article has no published date.</description>
    </item>
    <item>
      <title>Item with no link</title>
      <description>This item has no URL.</description>
    </item>
  </channel>
</rss>"""

VALID_SOURCE_CFG = {
    "name": "Google News AU",
    "type": "news",
    "trust_tier": "aggregator",
    "url": "https://news.google.com/rss/search?q=car+loan",
    "region": "AU",
    "source_weight": 0.5,
    "max_items": 50,
}

OFFICIAL_SOURCE_CFG = {
    "name": "ASIC Media",
    "type": "regulator",
    "trust_tier": "official",
    "url": "https://asic.gov.au/rss",
    "region": "AU",
    "source_weight": 1.0,
    "max_items": 20,
}


# ── validate_source_config ────────────────────────────────────

def test_valid_config_passes():
    validate_source_config(VALID_SOURCE_CFG)  # no exception


def test_missing_required_field_raises():
    bad = {k: v for k, v in VALID_SOURCE_CFG.items() if k != "trust_tier"}
    with pytest.raises(ValueError, match="trust_tier"):
        validate_source_config(bad)


def test_invalid_trust_tier_raises():
    bad = {**VALID_SOURCE_CFG, "trust_tier": "unknown_tier"}
    with pytest.raises(ValueError, match="trust_tier"):
        validate_source_config(bad)


def test_invalid_source_type_raises():
    bad = {**VALID_SOURCE_CFG, "type": "blog"}
    with pytest.raises(ValueError, match="type"):
        validate_source_config(bad)


def test_invalid_region_raises():
    bad = {**VALID_SOURCE_CFG, "region": "NZ"}
    with pytest.raises(ValueError, match="region"):
        validate_source_config(bad)


def test_empty_url_raises():
    bad = {**VALID_SOURCE_CFG, "url": ""}
    with pytest.raises(ValueError, match="url"):
        validate_source_config(bad)


def test_non_http_url_raises():
    bad = {**VALID_SOURCE_CFG, "url": "ftp://example.com/feed"}
    with pytest.raises(ValueError, match="url"):
        validate_source_config(bad)


def test_source_weight_out_of_range_raises():
    bad = {**VALID_SOURCE_CFG, "source_weight": 99}
    with pytest.raises(ValueError, match="source_weight"):
        validate_source_config(bad)


def test_source_weight_negative_raises():
    bad = {**VALID_SOURCE_CFG, "source_weight": -0.1}
    with pytest.raises(ValueError, match="source_weight"):
        validate_source_config(bad)


def test_max_items_zero_raises():
    bad = {**VALID_SOURCE_CFG, "max_items": 0}
    with pytest.raises(ValueError, match="max_items"):
        validate_source_config(bad)


def test_max_items_negative_raises():
    bad = {**VALID_SOURCE_CFG, "max_items": -1}
    with pytest.raises(ValueError, match="max_items"):
        validate_source_config(bad)


def test_valid_optional_fields_pass():
    validate_source_config({**VALID_SOURCE_CFG, "source_weight": 0.0})
    validate_source_config({**VALID_SOURCE_CFG, "source_weight": 1.0})
    validate_source_config({**VALID_SOURCE_CFG, "max_items": 1})


# ── _parse_rss ────────────────────────────────────────────────

def test_parse_rss_returns_raw_items():
    items = _parse_rss(SAMPLE_RSS, "Google News AU", "news", "aggregator", 0.5, "AU")
    # item with no link is skipped; 3 valid items
    assert len(items) == 3
    assert all(isinstance(i, RawItem) for i in items)


def test_parse_rss_correct_fields():
    items = _parse_rss(SAMPLE_RSS, "Google News AU", "news", "aggregator", 0.5, "AU")
    first = items[0]
    assert first.title == "ASIC cracks down on car loan brokers over irresponsible lending"
    assert first.source_name == "Google News AU"
    assert first.source_type == "news"
    assert first.trust_tier == "aggregator"
    assert first.source_weight == 0.5
    assert first.region == "AU"
    assert first.published_at is not None
    assert first.published_at.year == 2026


def test_trust_tier_flows_from_source_config():
    items = _parse_rss(SAMPLE_RSS, "ASIC Media", "regulator", "official", 1.0, "AU")
    assert all(i.trust_tier == "official" for i in items)
    assert all(i.source_weight == 1.0 for i in items)


def test_publisher_extracted_from_rss_source_element():
    items = _parse_rss(SAMPLE_RSS, "Google News AU", "news", "aggregator", 0.5, "AU")
    first = items[0]
    assert first.raw_metadata["publisher_name"] == "Australian Financial Review"
    assert first.raw_metadata["publisher_url"] == "https://www.afr.com"


def test_aggregator_canonical_url_is_none():
    items = _parse_rss(SAMPLE_RSS, "Google News AU", "news", "aggregator", 0.5, "AU")
    assert all(i.canonical_url is None for i in items)


def test_official_canonical_url_is_link():
    items = _parse_rss(SAMPLE_RSS, "ASIC Media", "regulator", "official", 1.0, "AU")
    assert all(i.canonical_url == i.url for i in items)


def test_aggregator_name_in_metadata():
    items = _parse_rss(SAMPLE_RSS, "Google News AU", "news", "aggregator", 0.5, "AU")
    assert items[0].raw_metadata["aggregator_name"] == "Google News AU"


def test_official_source_aggregator_name_is_none():
    items = _parse_rss(SAMPLE_RSS, "ASIC Media", "regulator", "official", 1.0, "AU")
    assert items[0].raw_metadata["aggregator_name"] is None


def test_missing_date_is_none():
    items = _parse_rss(SAMPLE_RSS, "Google News AU", "news", "aggregator", 0.5, "AU")
    no_date = next(i for i in items if "no date" in i.title.lower())
    assert no_date.published_at is None


def test_item_with_no_link_skipped():
    items = _parse_rss(SAMPLE_RSS, "Google News AU", "news", "aggregator", 0.5, "AU")
    titles = [i.title for i in items]
    assert "Item with no link" not in titles


def test_stable_ids():
    items1 = _parse_rss(SAMPLE_RSS, "Google News AU", "news", "aggregator", 0.5, "AU")
    items2 = _parse_rss(SAMPLE_RSS, "Google News AU", "news", "aggregator", 0.5, "AU")
    for i1, i2 in zip(items1, items2):
        assert i1.id == i2.id


def test_html_stripped_from_body():
    items = _parse_rss(SAMPLE_RSS, "Google News AU", "news", "aggregator", 0.5, "AU")
    assert "<p>" not in items[0].body
    assert "ASIC launched enforcement action" in items[0].body
    assert "<a " not in items[1].body


def test_malformed_xml_returns_empty():
    items = _parse_rss("<not valid xml<<", "Bad Source", "news", "aggregator", 0.5, "AU")
    assert items == []


def test_max_items_cap():
    with patch("csc.connectors.rss_connector._fetch_with_retry", return_value=SAMPLE_RSS):
        items = fetch_rss({**VALID_SOURCE_CFG, "max_items": 1})
    assert len(items) == 1


# ── fetch_all_sources ─────────────────────────────────────────

def test_fetch_all_sources_invalid_config_raises_before_network():
    bad_sources = [{**VALID_SOURCE_CFG, "trust_tier": "invalid"}]
    with pytest.raises(ValueError):
        fetch_all_sources(bad_sources)


def test_fetch_all_sources_continues_after_network_failure():
    def fake_fetch(source_cfg):
        if source_cfg["name"] == "Google News AU":
            raise urllib.error.URLError("connection refused")
        return []

    with patch("csc.connectors.rss_connector.fetch_rss", side_effect=fake_fetch):
        result = fetch_all_sources([VALID_SOURCE_CFG, OFFICIAL_SOURCE_CFG])

    assert result == []  # both returned empty/failed but no exception raised


def test_fetch_all_sources_combines_results():
    def fake_fetch(source_cfg):
        return _parse_rss(SAMPLE_RSS, source_cfg["name"], source_cfg["type"],
                          source_cfg["trust_tier"], source_cfg["source_weight"], source_cfg["region"])

    with patch("csc.connectors.rss_connector.fetch_rss", side_effect=fake_fetch):
        result = fetch_all_sources([VALID_SOURCE_CFG, OFFICIAL_SOURCE_CFG])

    assert len(result) == 6  # 3 items × 2 sources


# ── _parse_date ───────────────────────────────────────────────

def test_parse_date_rfc2822():
    d = _parse_date("Mon, 18 May 2026 08:30:00 GMT")
    assert d is not None
    assert d.year == 2026 and d.month == 5 and d.day == 18


def test_parse_date_iso8601():
    d = _parse_date("2026-05-18T08:30:00Z")
    assert d is not None
    assert d.year == 2026


def test_parse_date_empty_string():
    assert _parse_date("") is None


def test_parse_date_garbage():
    assert _parse_date("not a date at all") is None


# ── _strip_html ───────────────────────────────────────────────

def test_strip_html_removes_tags():
    assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"


def test_strip_html_no_tags():
    assert _strip_html("No tags here") == "No tags here"


def test_strip_html_empty():
    assert _strip_html("") == ""


def test_strip_html_collapses_whitespace():
    assert _strip_html("<p>  lots   of   space  </p>") == "lots of space"
