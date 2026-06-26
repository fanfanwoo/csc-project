"""
Evidence-state stage tests — labelling only (v1a does no fetching).

Covers the trust_tier → evidence_category derivation and the per-category policy
for the two live sources (ASIC official, Google News aggregator), plus the
publisher stub branch that v1b will fill in.
"""
from datetime import datetime, timezone

import pytest

from csc.pipeline.evidence_state import label_evidence
from csc.schemas.items import FilteredItem

NOW = datetime.now(timezone.utc)


def _filtered_item(**overrides) -> FilteredItem:
    base = dict(
        id="abc",
        url="https://example.com/1",
        canonical_url="https://example.com/1",
        title="Headline",
        body="Some body text.",
        source_name="Source",
        source_type="news",
        trust_tier="aggregator",
        region="AU",
        published_at=NOW,
        fetched_at=NOW,
        raw_metadata={},
    )
    base.update(overrides)
    return FilteredItem(**base)


# ── ASIC: official / full_body ────────────────────────────────


def test_official_item_labelled_full_body():
    item = _filtered_item(
        source_name="ASIC Media",
        source_type="regulator",
        trust_tier="official",
        canonical_url="https://asic.gov.au/1",
        body="A full regulator media release with complete article body text.",
    )
    label_evidence([item])
    assert item.evidence_category == "official"
    assert item.evidence_source == "official_page"
    assert item.evidence_level == "full_body"
    assert item.enrichment_status == "success"
    assert item.enrichment_reason == "body_present"


# ── Google News: aggregator / headline_only / skipped ─────────


def test_aggregator_item_labelled_headline_only_and_skipped():
    item = _filtered_item(
        source_name="Google News AU",
        trust_tier="aggregator",
        canonical_url=None,
        body="Borrowers caught out with high-interest car loans",  # promo snippet, not evidence
    )
    label_evidence([item])
    assert item.evidence_category == "aggregator"
    assert item.evidence_source == "aggregator_rss"
    assert item.evidence_level == "headline_only"
    assert item.enrichment_status == "skipped"
    assert item.enrichment_reason == "aggregator_url_not_fetchable"


def test_aggregator_never_excerpt_even_with_long_body():
    # Long promo text must still be headline_only — it is not article evidence.
    item = _filtered_item(trust_tier="aggregator", body="x" * 2000)
    label_evidence([item])
    assert item.evidence_level == "headline_only"
    assert item.enrichment_status == "skipped"


# ── trust_tier → evidence_category derivation ─────────────────


@pytest.mark.parametrize(
    "trust_tier,expected_category",
    [
        ("official", "official"),
        ("primary_company", "publisher"),
        ("major_news", "publisher"),
        ("trade_press", "publisher"),
        ("aggregator", "aggregator"),
        ("social", "aggregator"),
    ],
)
def test_category_derivation(trust_tier, expected_category):
    item = _filtered_item(trust_tier=trust_tier, body="x" * 700)
    label_evidence([item])
    assert item.evidence_category == expected_category


def test_unknown_trust_tier_falls_back_to_aggregator():
    # Never silently promote an unknown tier to a stronger bucket.
    item = _filtered_item(trust_tier="something_new")
    label_evidence([item])
    assert item.evidence_category == "aggregator"
    assert item.evidence_level == "headline_only"


# ── Publisher branch: labels from body, preserves enrich's provenance ─────────
# evidence_state owns evidence_*; enrich_fetch (runs before) owns enrichment_*.


def test_publisher_long_body_is_full_body():
    # Simulate enrich_fetch having populated a full body + its provenance.
    item = _filtered_item(
        trust_tier="major_news", body="x" * 700,
        enrichment_status="success", enrichment_reason="body_found",
    )
    label_evidence([item])
    assert item.evidence_category == "publisher"
    assert item.evidence_source == "publisher_rss"
    assert item.evidence_level == "full_body"
    # enrich's provenance is preserved, not overwritten
    assert item.enrichment_status == "success"
    assert item.enrichment_reason == "body_found"


def test_publisher_short_body_is_excerpt():
    item = _filtered_item(
        trust_tier="trade_press", body="Short excerpt.",
        enrichment_status="success", enrichment_reason="body_found",
    )
    label_evidence([item])
    assert item.evidence_level == "excerpt"


def test_publisher_empty_body_keeps_enrich_failed_status():
    # enrich_fetch failed to get a body (paywall/network); evidence_state labels
    # headline_only and must KEEP enrich's failed status/reason.
    item = _filtered_item(
        trust_tier="primary_company", body="",
        enrichment_status="failed", enrichment_reason="paywalled_or_empty",
    )
    label_evidence([item])
    assert item.evidence_level == "headline_only"
    assert item.enrichment_status == "failed"
    assert item.enrichment_reason == "paywalled_or_empty"


# ── Defaults / contract ───────────────────────────────────────


def test_returns_same_list():
    items = [_filtered_item()]
    assert label_evidence(items) is items


def test_unprocessed_item_has_weakest_defaults():
    # Before evidence_state runs, fields must default to the weakest values.
    item = _filtered_item()
    assert item.evidence_category == "aggregator"
    assert item.evidence_level == "headline_only"
    assert item.evidence_source == "unknown"
    assert item.enrichment_status == "skipped"
    assert item.enrichment_reason is None
