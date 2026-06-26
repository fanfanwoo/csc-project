"""
Shared trust_tier → evidence_category mapping.

Single source of truth so evidence_state, enrich_fetch, and deduplicate all route
on the same three-bucket category and never key on the six-value trust_tier directly.
"""

# trust_tier (6 values) → evidence_category (3 buckets).
_CATEGORY_BY_TRUST_TIER = {
    "official": "official",
    "primary_company": "publisher",
    "major_news": "publisher",
    "trade_press": "publisher",
    "aggregator": "aggregator",
    "social": "aggregator",
}


def category_for(trust_tier: str) -> str:
    """Map a trust_tier to its evidence_category. Unknown tiers fall back to the
    weakest bucket — never silently 'official'."""
    return _CATEGORY_BY_TRUST_TIER.get(trust_tier, "aggregator")
