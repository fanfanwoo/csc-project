"""
Evidence-state stage — labels evidence quality. Runs after dedup, before classify.

v1a does NO fetching. It only *labels* each item's evidence provenance so the verify
gate (Phase 2b) can route on it. Real body-fetching arrives in v1b as a separate
`enrich_fetch` module; the publisher branch here is a deliberate stub that v1b fills
in without restructuring.

Routing keys on the three-bucket `evidence_category` derived from the six-value
`trust_tier` — never on `trust_tier` directly.
"""

from csc.schemas.items import FilteredItem
from csc.utils.logging import get_logger

logger = get_logger(__name__)

# trust_tier (6 values) → evidence_category (3 buckets). The verify gate routes on
# the bucket, so this mapping is the single place the two vocabularies meet.
_CATEGORY_BY_TRUST_TIER = {
    "official": "official",
    "primary_company": "publisher",
    "major_news": "publisher",
    "trade_press": "publisher",
    "aggregator": "aggregator",
    "social": "aggregator",
}

# A publisher body at/above this length is treated as a full article rather than an
# excerpt. Only consulted in the publisher branch (no such source in v1a).
_FULL_BODY_MIN_CHARS = 600


def label_evidence(items: list[FilteredItem]) -> list[FilteredItem]:
    """Populate the evidence_* / enrichment_* fields on each item in place."""
    for item in items:
        item.evidence_category = _category_for(item.trust_tier)
        if item.evidence_category == "official":
            _label_official(item)
        elif item.evidence_category == "publisher":
            _label_publisher(item)
        else:
            _label_aggregator(item)

    logger.info(
        "evidence labelled",
        extra={
            "total": len(items),
            "official": sum(1 for i in items if i.evidence_category == "official"),
            "publisher": sum(1 for i in items if i.evidence_category == "publisher"),
            "aggregator": sum(1 for i in items if i.evidence_category == "aggregator"),
        },
    )
    return items


def _category_for(trust_tier: str) -> str:
    # Unknown tiers fall back to the weakest bucket — never silently "official".
    return _CATEGORY_BY_TRUST_TIER.get(trust_tier, "aggregator")


def _label_official(item: FilteredItem) -> None:
    # Official sources (ASIC) already carry full bodies from the two-stage fetch.
    item.evidence_source = "official_page"
    item.evidence_level = "full_body"
    item.enrichment_status = "success"
    item.enrichment_reason = "body_present"


def _label_publisher(item: FilteredItem) -> None:
    # STUB for v1a: no publisher source exists yet. We label from the body already
    # present, but do NOT fetch. v1b's enrich_fetch fills in the actual fetch here
    # (try-fetch → parse → set level/status from the result) without restructuring.
    item.evidence_source = "publisher_rss"
    if item.body and len(item.body) >= _FULL_BODY_MIN_CHARS:
        item.evidence_level = "full_body"
        item.enrichment_reason = "body_found"
    elif item.body:
        item.evidence_level = "excerpt"
        item.enrichment_reason = "body_found"
    else:
        item.evidence_level = "headline_only"
        item.enrichment_reason = "parse_failed"
    item.enrichment_status = "success" if item.body else "failed"


def _label_aggregator(item: FilteredItem) -> None:
    # Google News: the RSS <description> is publisher promo text, not article
    # evidence — treat as headline_only. The encoded redirect URL is not fetchable,
    # so never attempt it (verified live, June 2026).
    item.evidence_source = "aggregator_rss"
    item.evidence_level = "headline_only"
    item.enrichment_status = "skipped"
    item.enrichment_reason = "aggregator_url_not_fetchable"
