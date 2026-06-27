"""
v1b operational metrics — the leading indicators to watch across runs.

Computed from the stage item-lists at the end of a run and stored on RunLog.metrics
(persisted to data/logs/{run_id}.jsonl). These answer the questions v1b left open:
was Australian Broker a good pick, is title-only filtering dropping too much, does
enrich succeed, is Phase 3 (publisher-over-aggregator) firing, did Phase 0 release
official items. Read them across runs with csc.tools.run_metrics_report.
"""

from csc.pipeline.verify import count_official_released
from csc.utils.evidence import category_for


def compute(
    *,
    raw: list,
    filtered_kept: list,
    labelled: list,
    held: list,
    passed: list,
    dedup_stats: dict,
    high_impact_threshold: float,
) -> dict:
    """Build the metrics dict from stage outputs. Publisher items are identified by
    evidence_category (derived from trust_tier), never by source name."""
    pub_raw = [i for i in raw if category_for(i.trust_tier) == "publisher"]
    pub_kept = [i for i in filtered_kept if category_for(i.trust_tier) == "publisher"]
    pub_enriched = [i for i in labelled if category_for(i.trust_tier) == "publisher"]

    return {
        # Source value + filter pressure (publisher = Australian Broker today)
        "publisher_fetched": len(pub_raw),
        "publisher_dropped_filter": len(pub_raw) - len(pub_kept),  # title-only at filter time
        # Enrich health
        "enrich_attempted": len(pub_enriched),
        "enrich_success": sum(1 for i in pub_enriched if i.enrichment_status == "success"),
        "enrich_failed": sum(1 for i in pub_enriched if i.enrichment_status == "failed"),
        "enrich_excerpt": sum(1 for i in pub_enriched if i.evidence_level == "excerpt"),
        # Gate behaviour
        "held_headline_only_high_impact": sum(
            1 for i in held if "headline_only_high_impact" in (i.human_review_reason or "")
        ),
        "official_released": count_official_released(passed, high_impact_threshold),
        # Phase 3 payoff
        "dedup_publisher_over_aggregator": dedup_stats.get("publisher_over_aggregator", 0),
    }
