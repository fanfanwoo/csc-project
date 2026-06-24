"""
Verify stage tests — human-review flag policy.

Relocated from test_classify.py in Day 2 v1a Phase 1. These call
verify.apply_review_flags directly on ClassifiedItem fixtures, rather than
asserting flags as a side effect of classify_items.
"""
from datetime import datetime, timezone

from csc.pipeline.verify import apply_review_flags
from csc.schemas.items import ClassifiedItem

NOW = datetime.now(timezone.utc)
CONFIDENCE_FLOOR = 0.5


def _classified_item(**overrides) -> ClassifiedItem:
    base = dict(
        id="abc",
        url="https://example.com/1",
        canonical_url="https://example.com/1",
        title="ASIC tightens car loan rules",
        body="Regulator issues new lending obligations for vehicle finance.",
        source_name="ASIC Media",
        source_type="regulator",
        region="AU",
        published_at=NOW,
        fetched_at=NOW,
        raw_metadata={},
        domain="policy",
        signal_type="regulatory_change",
        relevance_score=0.9,
        novelty_score=0.7,
        impact_score=0.85,
        urgency_score=0.8,
        confidence=0.88,
        tags=["ASIC", "lending"],
        rationale="New ASIC lending obligations directly affect car finance providers.",
        evidence_quote="new guidance on responsible lending",
        inference_note=None,
    )
    base.update(overrides)
    return ClassifiedItem(**base)


def test_review_flag_low_confidence():
    item = _classified_item(confidence=0.3, impact_score=0.3, rationale="Minor update.")
    apply_review_flags([item], CONFIDENCE_FLOOR)
    assert item.human_review_flag is True
    assert "low_confidence" in item.human_review_reason


def test_review_flag_sensitive_domain():
    # "lending" appears in the rationale
    item = _classified_item(impact_score=0.3, duplicate_count=2, duplicate_source_names=["Reuters"])
    apply_review_flags([item], CONFIDENCE_FLOOR)
    assert item.human_review_flag is True
    assert "sensitive_domain" in item.human_review_reason


def test_review_flag_single_source_high_impact():
    item = _classified_item(
        duplicate_count=0, confidence=0.9, impact_score=0.9, rationale="No keywords here."
    )
    apply_review_flags([item], CONFIDENCE_FLOOR)
    assert item.human_review_flag is True
    assert "single_source_high_impact" in item.human_review_reason


def test_review_flag_large_inference_leap():
    item = _classified_item(
        confidence=0.9,
        impact_score=0.3,
        duplicate_count=2,
        rationale="Minor market update.",
        inference_note="x" * 201,
    )
    apply_review_flags([item], CONFIDENCE_FLOOR)
    assert item.human_review_flag is True
    assert "large_inference_leap" in item.human_review_reason


def test_no_review_flag_when_clean():
    item = _classified_item(
        duplicate_count=2,
        duplicate_source_names=["Reuters"],
        confidence=0.9,
        impact_score=0.5,
        rationale="Minor market update.",
    )
    apply_review_flags([item], CONFIDENCE_FLOOR)
    assert item.human_review_flag is False
    assert item.human_review_reason is None


def test_apply_review_flags_returns_same_list():
    items = [_classified_item(confidence=0.9, impact_score=0.5, rationale="Clean.")]
    result = apply_review_flags(items, CONFIDENCE_FLOOR)
    assert result is items
