"""
Tests for the ASIC official_page_connector.
All network calls are mocked — no live HTTP.
"""

import json
from datetime import datetime, timezone
from unittest.mock import patch, call

import pytest

# Suppress the polite inter-request delay so the test suite doesn't slow down.
@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("csc.connectors.official_page_connector.time.sleep", lambda _: None)


from csc.connectors.official_page_connector import (
    ASIC_BASE_URL,
    DETAIL_BODY_ID,
    fetch_official_page,
    _extract_body,
    _parse_date,
    _strip_html,
)
from csc.schemas.items import RawItem

# ── Fixtures ──────────────────────────────────────────────────

VALID_SOURCE_CFG = {
    "name": "ASIC Media",
    "type": "regulator",
    "trust_tier": "official",
    "connector": "official_page",
    "url": "https://download.asic.gov.au/scripts/newsroom/newsroom-all.json",
    "region": "AU",
    "source_weight": 1.0,
    "max_items": 2,
}

LISTING_JSON = json.dumps([
    {
        "id": 100,
        "name": "26-001MR ASIC takes action on irresponsible car lending",
        "publishedDate": "2026-05-30T10:00:00Z",
        "documentNumber": "26-001MR",
        "url": "/about-asic/news-centre/find-a-media-release/2026-releases/26-001mr-car-lending/",
        "metaDescription": "ASIC has commenced action against a car lender for irresponsible lending.",
        "summary": "<p>Summary paragraph.</p>",
        "metaSubject": ["consumer credit", "car loans"],
        "metaFunction": ["enforcement"],
    },
    {
        "id": 101,
        "name": "26-002MR Update on consumer credit obligations",
        "publishedDate": "2026-05-28T08:00:00Z",
        "documentNumber": "26-002MR",
        "url": "/about-asic/news-centre/find-a-media-release/2026-releases/26-002mr-consumer-credit/",
        "metaDescription": "ASIC updates guidance on consumer credit.",
        "summary": "<p>Another summary.</p>",
        "metaSubject": ["consumer credit"],
        "metaFunction": ["guidance"],
    },
])

DETAIL_HTML_1 = f"""<!DOCTYPE html>
<html><body>
<main id="nh-container">
  <article id="nh-mr-container">
    <div id="{DETAIL_BODY_ID}">
      <p>ASIC has commenced civil penalty proceedings in the Federal Court against CarFinanceCo.</p>
      <p>The proceedings allege the lender failed responsible lending obligations on over 5,000 loans.</p>
      <h2>Background</h2>
      <p>The responsible lending obligations require lenders to assess whether a loan is suitable.</p>
    </div>
  </article>
</main>
</body></html>"""

DETAIL_HTML_2 = f"""<!DOCTYPE html>
<html><body>
<main id="nh-container">
  <article id="nh-mr-container">
    <div id="{DETAIL_BODY_ID}">
      <p>ASIC has updated its guidance on consumer credit obligations effective July 2026.</p>
    </div>
  </article>
</main>
</body></html>"""

DETAIL_URL_1 = ASIC_BASE_URL + "/about-asic/news-centre/find-a-media-release/2026-releases/26-001mr-car-lending/"
DETAIL_URL_2 = ASIC_BASE_URL + "/about-asic/news-centre/find-a-media-release/2026-releases/26-002mr-consumer-credit/"


def _mock_fetch(url, source_name, **kwargs):
    """Return fixture content keyed by URL."""
    if "newsroom-all.json" in url:
        return LISTING_JSON
    if "26-001mr" in url:
        return DETAIL_HTML_1
    if "26-002mr" in url:
        return DETAIL_HTML_2
    return None


# ── fetch_official_page ───────────────────────────────────────

def test_returns_correct_raw_items():
    with patch("csc.connectors.official_page_connector.fetch_with_retry", side_effect=_mock_fetch):
        items = fetch_official_page(VALID_SOURCE_CFG)

    assert len(items) == 2
    assert all(isinstance(i, RawItem) for i in items)


def test_correct_url_and_canonical_url():
    with patch("csc.connectors.official_page_connector.fetch_with_retry", side_effect=_mock_fetch):
        items = fetch_official_page(VALID_SOURCE_CFG)

    first = items[0]
    assert first.url == DETAIL_URL_1
    assert first.canonical_url == DETAIL_URL_1


def test_title_extracted():
    with patch("csc.connectors.official_page_connector.fetch_with_retry", side_effect=_mock_fetch):
        items = fetch_official_page(VALID_SOURCE_CFG)

    assert "car lending" in items[0].title.lower()


def test_full_body_text_extracted():
    with patch("csc.connectors.official_page_connector.fetch_with_retry", side_effect=_mock_fetch):
        items = fetch_official_page(VALID_SOURCE_CFG)

    body = items[0].body
    assert "civil penalty proceedings" in body
    assert "5,000 loans" in body
    assert "responsible lending obligations" in body
    # No HTML tags in body
    assert "<p>" not in body
    assert "<h2>" not in body


def test_source_metadata_correct():
    with patch("csc.connectors.official_page_connector.fetch_with_retry", side_effect=_mock_fetch):
        items = fetch_official_page(VALID_SOURCE_CFG)

    first = items[0]
    assert first.source_name == "ASIC Media"
    assert first.source_type == "regulator"
    assert first.trust_tier == "official"
    assert first.source_weight == 1.0
    assert first.region == "AU"


def test_published_at_parsed():
    with patch("csc.connectors.official_page_connector.fetch_with_retry", side_effect=_mock_fetch):
        items = fetch_official_page(VALID_SOURCE_CFG)

    first = items[0]
    assert first.published_at is not None
    assert first.published_at.year == 2026
    assert first.published_at.month == 5
    assert first.published_at.day == 30


def test_raw_metadata_populated():
    with patch("csc.connectors.official_page_connector.fetch_with_retry", side_effect=_mock_fetch):
        items = fetch_official_page(VALID_SOURCE_CFG)

    meta = items[0].raw_metadata
    assert meta["release_id"] == 100
    assert meta["document_number"] == "26-001MR"
    assert "consumer credit" in meta["meta_subject"]
    assert meta["meta_function"] == ["enforcement"]


def test_max_items_cap():
    big_listing = json.dumps([
        {
            "id": i,
            "name": f"Release {i}",
            "publishedDate": "2026-05-01T00:00:00Z",
            "url": f"/about-asic/news-centre/find-a-media-release/2026-releases/release-{i}/",
            "metaDescription": f"Description {i}",
            "summary": "",
            "documentNumber": f"26-{i:03d}MR",
            "metaSubject": [],
            "metaFunction": [],
        }
        for i in range(10)
    ])

    def mock_fetch_big(url, source_name, **kwargs):
        if "newsroom-all.json" in url:
            return big_listing
        return f"<html><body><div id='{DETAIL_BODY_ID}'>Body {url}</div></body></html>"

    cfg = {**VALID_SOURCE_CFG, "max_items": 3}
    with patch("csc.connectors.official_page_connector.fetch_with_retry", side_effect=mock_fetch_big):
        items = fetch_official_page(cfg)

    assert len(items) == 3


def test_zero_item_listing_logs_warning(caplog):
    import logging
    with patch("csc.connectors.official_page_connector.fetch_with_retry", return_value="[]"):
        with caplog.at_level(logging.WARNING, logger="csc.connectors.official_page"):
            items = fetch_official_page(VALID_SOURCE_CFG)

    assert items == []
    assert any("zero items" in r.message for r in caplog.records)


def test_detail_fetch_failure_skips_item_gracefully():
    """Detail page 404 → skip that item; other items still returned."""
    def mock_fetch_partial(url, source_name, **kwargs):
        if "newsroom-all.json" in url:
            return LISTING_JSON
        if "26-001mr" in url:
            return None  # simulate network failure on first detail page
        if "26-002mr" in url:
            return DETAIL_HTML_2
        return None

    with patch("csc.connectors.official_page_connector.fetch_with_retry", side_effect=mock_fetch_partial):
        items = fetch_official_page(VALID_SOURCE_CFG)

    # Second item returned; first falls back to metaDescription (not skipped — body fallback kicks in)
    assert len(items) == 2
    # First item used metaDescription fallback
    assert "irresponsible lending" in items[0].body


def test_fallback_to_meta_description_when_body_empty():
    """If detail page has no DETAIL_BODY_ID div, falls back to metaDescription."""
    empty_body_html = "<html><body><main><article></article></main></body></html>"

    def mock_fetch_empty(url, source_name, **kwargs):
        if "newsroom-all.json" in url:
            return LISTING_JSON
        return empty_body_html

    with patch("csc.connectors.official_page_connector.fetch_with_retry", side_effect=mock_fetch_empty):
        items = fetch_official_page(VALID_SOURCE_CFG)

    assert len(items) == 2
    assert items[0].body == "ASIC has commenced action against a car lender for irresponsible lending."


def test_listing_fetch_failure_returns_empty():
    with patch("csc.connectors.official_page_connector.fetch_with_retry", return_value=None):
        items = fetch_official_page(VALID_SOURCE_CFG)

    assert items == []


def test_invalid_config_raises():
    bad_cfg = {**VALID_SOURCE_CFG, "trust_tier": "unknown"}
    with pytest.raises(ValueError, match="trust_tier"):
        fetch_official_page(bad_cfg)


# ── _extract_body ─────────────────────────────────────────────

def test_extract_body_returns_text():
    body = _extract_body(DETAIL_HTML_1)
    assert "civil penalty proceedings" in body
    assert "<p>" not in body


def test_extract_body_missing_div_returns_empty():
    html = "<html><body><div id='other'>stuff</div></body></html>"
    assert _extract_body(html) == ""


# ── _parse_date ───────────────────────────────────────────────

def test_parse_date_iso_z():
    d = _parse_date("2026-05-30T10:00:00Z")
    assert d is not None
    assert d.year == 2026 and d.month == 5 and d.day == 30
    assert d.tzinfo is not None


def test_parse_date_none():
    assert _parse_date(None) is None


def test_parse_date_empty():
    assert _parse_date("") is None


def test_parse_date_garbage():
    assert _parse_date("not-a-date") is None


# ── _strip_html ───────────────────────────────────────────────

def test_strip_html_removes_tags():
    assert "Summary paragraph." in _strip_html("<p>Summary paragraph.</p>")
    assert "<p>" not in _strip_html("<p>Summary paragraph.</p>")


def test_strip_html_plain_text_unchanged():
    assert _strip_html("Plain text here") == "Plain text here"
