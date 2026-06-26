"""
Verify stage tests — human-review flag policy.

Relocated from test_classify.py in Day 2 v1a Phase 1. These call
verify.apply_review_flags directly on ClassifiedItem fixtures, rather than
asserting flags as a side effect of classify_items.
"""
from datetime import datetime, timezone

from csc.pipeline.verify import apply_review_flags, verify_items
from csc.schemas.items import ClassifiedItem

NOW = datetime.now(timezone.utc)
CONFIDENCE_FLOOR = 0.5
HIGH_IMPACT = 0.8


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


def test_long_inference_note_no_longer_holds():
    # large_inference_leap was dropped in v1a (length is a weak proxy) — a long
    # inference note alone must NOT flag or hold an otherwise clean item.
    item = _classified_item(
        confidence=0.9,
        impact_score=0.3,
        duplicate_count=2,
        rationale="Minor market update.",
        inference_note="x" * 400,
    )
    apply_review_flags([item], CONFIDENCE_FLOOR)
    assert item.human_review_flag is False


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


# ── verify_items partition (the gate behaviour) ───────────────


def _clean_asic(**overrides):
    # Strong, well-evidenced, corroborated official item — should pass.
    base = dict(
        evidence_level="full_body",
        confidence=0.9,
        impact_score=0.5,
        duplicate_count=2,
        duplicate_source_names=["ABC", "AFR"],
        rationale="Routine market update with no stakes keywords.",
        title="Vehicle sales tick up in Q2",
    )
    base.update(overrides)
    return _classified_item(**base)


def test_clean_item_passes():
    item = _clean_asic()
    passed, held = verify_items([item], CONFIDENCE_FLOOR, HIGH_IMPACT)
    assert passed == [item]
    assert held == []
    assert item.human_review_flag is False


def test_low_confidence_held():
    item = _clean_asic(confidence=0.3)
    passed, held = verify_items([item], CONFIDENCE_FLOOR, HIGH_IMPACT)
    assert held == [item]
    assert item not in passed
    assert "low_confidence" in item.human_review_reason


def test_single_source_high_impact_held():
    item = _clean_asic(duplicate_count=0, duplicate_source_names=[], impact_score=0.9)
    passed, held = verify_items([item], CONFIDENCE_FLOOR, HIGH_IMPACT)
    assert held == [item]
    assert item not in passed
    assert "single_source_high_impact" in item.human_review_reason


def test_headline_only_high_impact_held():
    # Google-News-style: corroborated (so single_source does NOT fire) but the only
    # evidence is a headline — the new rule must hold it.
    item = _clean_asic(
        evidence_level="headline_only",
        impact_score=0.9,
        duplicate_count=2,
        source_name="Google News AU",
    )
    passed, held = verify_items([item], CONFIDENCE_FLOOR, HIGH_IMPACT)
    assert held == [item]
    assert item not in passed
    assert "headline_only_high_impact" in item.human_review_reason


def test_sensitive_domain_strong_item_passes_marked():
    # "lending" in rationale → sensitive_domain, but otherwise strong → passes WITH flag.
    item = _clean_asic(rationale="New responsible lending obligations for car finance.")
    passed, held = verify_items([item], CONFIDENCE_FLOOR, HIGH_IMPACT)
    assert passed == [item]
    assert held == []
    assert item.human_review_flag is True
    assert "sensitive_domain" in item.human_review_reason


def test_partition_keeps_held_out_of_pass_stream():
    clean = _clean_asic(id="clean-1")
    weak = _clean_asic(id="weak-1", confidence=0.2, title="Weak signal")
    passed, held = verify_items([clean, weak], CONFIDENCE_FLOOR, HIGH_IMPACT)
    passed_ids = {i.id for i in passed}
    held_ids = {i.id for i in held}
    assert held_ids.isdisjoint(passed_ids)
    assert weak in held
    assert clean in passed


def test_threshold_is_configurable():
    # impact 0.7 holds under a 0.6 threshold, passes under the default 0.8.
    item = lambda: _clean_asic(duplicate_count=0, duplicate_source_names=[], impact_score=0.7)
    _, held_low = verify_items([item()], CONFIDENCE_FLOOR, 0.6)
    passed_default, held_default = verify_items([item()], CONFIDENCE_FLOOR, 0.8)
    assert len(held_low) == 1
    assert len(passed_default) == 1 and held_default == []


# ── Phase 0: official + full_body exemption from single_source_high_impact ──


def _official_single_high(**overrides):
    # Official, full-body, single-source, high-impact — strong evidence, should pass.
    base = dict(
        evidence_category="official",
        evidence_level="full_body",
        duplicate_count=0,
        duplicate_source_names=[],
        impact_score=0.9,
        confidence=0.9,
        rationale="Routine regulator update with no stakes keywords.",
        title="ASIC publishes quarterly enforcement update",
    )
    base.update(overrides)
    return _clean_asic(**base)


def test_official_full_body_single_source_high_impact_passes():
    item = _official_single_high()
    passed, held = verify_items([item], CONFIDENCE_FLOOR, HIGH_IMPACT)
    assert passed == [item]
    assert held == []
    assert item.human_review_flag is False


def test_official_full_body_sensitive_passes_marked():
    item = _official_single_high(rationale="New responsible lending enforcement action.")
    passed, held = verify_items([item], CONFIDENCE_FLOOR, HIGH_IMPACT)
    assert passed == [item]
    assert held == []
    assert item.human_review_flag is True
    assert "sensitive_domain" in item.human_review_reason
    assert "single_source_high_impact" not in (item.human_review_reason or "")


def test_official_excerpt_high_impact_still_held():
    # Partial official evidence (excerpt, not full body) is NOT exempt.
    item = _official_single_high(evidence_level="excerpt")
    passed, held = verify_items([item], CONFIDENCE_FLOOR, HIGH_IMPACT)
    assert held == [item]
    assert item not in passed
    assert "single_source_high_impact" in item.human_review_reason


def test_non_official_full_body_single_source_still_held():
    # Publisher full-body single-source high-impact gets no exemption.
    item = _official_single_high(evidence_category="publisher")
    passed, held = verify_items([item], CONFIDENCE_FLOOR, HIGH_IMPACT)
    assert held == [item]
    assert item not in passed
    assert "single_source_high_impact" in item.human_review_reason
