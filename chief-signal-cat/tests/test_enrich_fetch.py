"""
enrich_fetch tests — deterministic publisher body fetch. HTTP is mocked; no network.
"""
from datetime import datetime, timezone
from unittest.mock import patch

from csc.pipeline.enrich_fetch import enrich
from csc.schemas.items import FilteredItem

NOW = datetime.now(timezone.utc)

SOURCES = [
    {"name": "Australian Broker", "body_selector": "div.article-detail"},
    {"name": "ASIC Media"},
    {"name": "Google News AU"},
]
CFG = {"fetch_delay": 0, "full_body_min_chars": 600}

ARTICLE_HTML = """
<html><head><meta property="og:description" content="standfirst"></head>
<body><div class="article-detail">
<p>First paragraph of the real article body.</p>
<p>Second paragraph with more detail.</p>
</div></body></html>
"""

PAYWALL_HTML = "<html><body><div class='paywall'>Subscribe to read.</div></body></html>"


def _item(**overrides) -> FilteredItem:
    base = dict(
        id="x", url="https://www.brokernews.com.au/news/a-289572.aspx",
        canonical_url="https://www.brokernews.com.au/news/a-289572.aspx",
        title="Negative gearing overhaul becomes law", body="",
        source_name="Australian Broker", source_type="news", trust_tier="trade_press",
        region="AU", published_at=NOW, fetched_at=NOW, raw_metadata={},
    )
    base.update(overrides)
    return FilteredItem(**base)


# ── publisher: fetch + extract ────────────────────────────────


def test_publisher_body_populated_on_success():
    item = _item()
    with patch("csc.pipeline.enrich_fetch.fetch_with_retry", return_value=ARTICLE_HTML) as m:
        enrich([item], CFG, SOURCES)
    m.assert_called_once_with(item.canonical_url, "Australian Broker")
    assert "First paragraph of the real article body." in item.body
    assert "Second paragraph" in item.body
    assert item.enrichment_status == "success"
    assert item.enrichment_reason == "body_found"


def test_publisher_paywalled_or_empty_leaves_body_empty():
    item = _item()
    with patch("csc.pipeline.enrich_fetch.fetch_with_retry", return_value=PAYWALL_HTML):
        enrich([item], CFG, SOURCES)
    assert item.body == ""
    assert item.enrichment_status == "failed"
    assert item.enrichment_reason == "paywalled_or_empty"


def test_publisher_network_failure_is_fetch_failed():
    item = _item()
    with patch("csc.pipeline.enrich_fetch.fetch_with_retry", return_value=None):
        enrich([item], CFG, SOURCES)
    assert item.body == ""
    assert item.enrichment_status == "failed"
    assert item.enrichment_reason == "fetch_failed"


def test_publisher_no_canonical_url_is_failed_no_fetch():
    item = _item(canonical_url=None)
    with patch("csc.pipeline.enrich_fetch.fetch_with_retry") as m:
        enrich([item], CFG, SOURCES)
    m.assert_not_called()
    assert item.enrichment_status == "failed"
    assert item.enrichment_reason == "no_canonical_url"


def test_extract_falls_back_to_og_description_without_selector_match():
    # No matching selector / article — falls back to og:description.
    item = _item()
    html = '<html><head><meta property="og:description" content="fallback body text"></head><body></body></html>'
    with patch("csc.pipeline.enrich_fetch.fetch_with_retry", return_value=html):
        enrich([item], CFG, SOURCES)
    assert item.body == "fallback body text"
    assert item.enrichment_status == "success"


# ── official / aggregator: never fetched ──────────────────────


def test_official_item_untouched():
    item = _item(source_name="ASIC Media", trust_tier="official",
                 body="ASIC full body already present.")
    with patch("csc.pipeline.enrich_fetch.fetch_with_retry") as m:
        enrich([item], CFG, SOURCES)
    m.assert_not_called()
    assert item.body == "ASIC full body already present."
    assert item.enrichment_status == "skipped"  # untouched default


def test_aggregator_item_untouched():
    item = _item(source_name="Google News AU", trust_tier="aggregator", canonical_url=None,
                 body="headline snippet")
    with patch("csc.pipeline.enrich_fetch.fetch_with_retry") as m:
        enrich([item], CFG, SOURCES)
    m.assert_not_called()
    assert item.body == "headline snippet"
    assert item.enrichment_status == "skipped"


def test_returns_same_list():
    items = [_item(source_name="ASIC Media", trust_tier="official")]
    with patch("csc.pipeline.enrich_fetch.fetch_with_retry"):
        assert enrich(items, CFG, SOURCES) is items
