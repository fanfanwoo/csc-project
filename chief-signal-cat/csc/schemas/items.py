from dataclasses import dataclass, field
from datetime import datetime
import hashlib


# ── Validation constants ──────────────────────────────────────

VALID_SOURCE_TYPES = {
    "news", "regulator", "competitor", "report",
    "social", "internal-note", "manual",
}

VALID_REGIONS = {"AU", "US", "EU", "global"}

VALID_DOMAINS = {
    "policy", "market", "auto", "finance",
    "AI", "competitor", "consumer", "other",
}

VALID_SIGNAL_TYPES = {
    "threat", "opportunity", "weak_signal", "trend",
    "regulatory_change", "competitor_move",
}

VALID_TRUST_TIERS = {
    "official", "primary_company", "major_news",
    "trade_press", "aggregator", "social",
}


# ── Stage 1: RawItem ──────────────────────────────────────────

@dataclass
class RawItem:
    # Identity
    id: str
    url: str
    canonical_url: str | None

    # Content
    title: str
    body: str

    # Source metadata — must come from source config, not guessed
    source_name: str
    source_type: str        # see VALID_SOURCE_TYPES
    trust_tier: str = "aggregator"   # see VALID_TRUST_TIERS
    source_weight: float = 0.5       # 0.0–1.0, used by scorer

    # Geography
    region: str = "AU"      # see VALID_REGIONS

    # Timestamps
    published_at: datetime | None = None
    fetched_at: datetime = field(default_factory=lambda: __import__('datetime').datetime.now(__import__('datetime').timezone.utc))

    # Extensible — source-specific fields, publisher provenance, etc.
    raw_metadata: dict = field(default_factory=dict)

    # Evidence provenance — populated by the evidence_state step, travels with the
    # signal through every later stage. Defaults are deliberately the "weakest"
    # values so an un-processed item is never mistaken for strong evidence.
    evidence_category: str = "aggregator"   # "official" | "publisher" | "aggregator" (derived from trust_tier)
    evidence_level: str = "headline_only"   # "full_body" | "excerpt" | "headline_only"
    evidence_source: str = "unknown"        # "official_page" | "publisher_rss" | "aggregator_rss"
    enrichment_status: str = "skipped"      # "success" | "skipped" | "failed"
    enrichment_reason: str | None = None    # e.g. "body_present" | "aggregator_url_not_fetchable" | "parse_failed"

    @staticmethod
    def generate_id(url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()[:16]


# ── Stage 2: FilteredItem ─────────────────────────────────────

@dataclass
class FilteredItem(RawItem):
    # Filter outcome
    filter_status: str = "kept"          # "kept" | "dropped" | "keep_with_warning"
    filter_reason: str | None = None     # None when kept cleanly; reason code otherwise
    matched_keywords: list[str] = field(default_factory=list)
    excluded_keywords: list[str] = field(default_factory=list)

    # Deduplication provenance — populated by Deduplicate module
    # duplicate_count > 0 = same signal from multiple sources (higher credibility)
    duplicate_count: int = 0
    duplicate_source_names: list[str] = field(default_factory=list)
    duplicate_item_ids: list[str] = field(default_factory=list)
    # How each duplicate was detected — "exact_url" | "fuzzy_title"; deduped list
    # Tells downstream how safely the merge was made (exact > fuzzy for scoring/review)
    dedup_methods: list[str] = field(default_factory=list)


# ── Stage 3: ClassifiedItem ───────────────────────────────────

@dataclass
class ClassifiedItem(FilteredItem):
    domain: str = "other"
    signal_type: str = "weak_signal"

    # Scores — all 0.0–1.0, assigned by LLM
    relevance_score: float = 0.0
    novelty_score: float = 0.0
    impact_score: float = 0.0
    urgency_score: float = 0.0
    confidence: float = 0.0     # LLM self-assessment only — not ground truth

    tags: list[str] = field(default_factory=list)
    rationale: str = ""
    evidence_quote: str | None = None   # source-supported excerpt or paraphrase
    inference_note: str | None = None   # what CSC inferred beyond source facts

    human_review_flag: bool = False
    human_review_reason: str | None = None


# ── Stage 4: ScoredItem ───────────────────────────────────────

@dataclass
class ScoredItem(ClassifiedItem):
    strategic_score: float = 0.0
    score_breakdown: dict = field(default_factory=dict)
    rank: int | None = None


# ── Classification failure ────────────────────────────────────
# Separate from pipeline data flow. Logged to data/logs/{run_id}_failures.jsonl.
# Never reaches the scorer.

@dataclass
class ClassificationFailure:
    item_id: str
    error_type: str         # json_parse_error | api_timeout | api_error | schema_validation_error
    error_message: str
    model: str
    attempted_at: datetime
    retry_count: int
