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
from csc.utils.evidence import category_for
from csc.utils.logging import get_logger

logger = get_logger(__name__)

# A publisher body at/above this length is treated as a full article rather than an
# excerpt. Aligned with enrich_fetch.full_body_min_chars.
_FULL_BODY_MIN_CHARS = 600


def label_evidence(items: list[FilteredItem]) -> list[FilteredItem]:
    """Populate the evidence_* fields on each item in place.

    evidence_state owns evidence_category / evidence_source / evidence_level.
    enrich_fetch (runs before this) owns enrichment_status / enrichment_reason and
    populates publisher bodies — those fields are left untouched here.
    """
    for item in items:
        item.evidence_category = category_for(item.trust_tier)
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


def _label_official(item: FilteredItem) -> None:
    # Official sources (ASIC) already carry full bodies from the two-stage fetch.
    item.evidence_source = "official_page"
    item.evidence_level = "full_body"
    item.enrichment_status = "success"
    item.enrichment_reason = "body_present"


def _label_publisher(item: FilteredItem) -> None:
    # enrich_fetch (runs before this) has already attempted the fetch and owns
    # enrichment_status / enrichment_reason. Here we only set the labels from the
    # resulting body length — do NOT overwrite enrich's fetch provenance.
    item.evidence_source = "publisher_rss"
    if item.body and len(item.body) >= _FULL_BODY_MIN_CHARS:
        item.evidence_level = "full_body"
    elif item.body:
        item.evidence_level = "excerpt"
    else:
        item.evidence_level = "headline_only"


def _label_aggregator(item: FilteredItem) -> None:
    # Google News: the RSS <description> is publisher promo text, not article
    # evidence — treat as headline_only. The encoded redirect URL is not fetchable,
    # so never attempt it (verified live, June 2026).
    item.evidence_source = "aggregator_rss"
    item.evidence_level = "headline_only"
    item.enrichment_status = "skipped"
    item.enrichment_reason = "aggregator_url_not_fetchable"
