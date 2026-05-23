from datetime import datetime, timezone

from csc.pipeline.score import score_items
from csc.schemas.items import ClassifiedItem

NOW = datetime.now(timezone.utc)
CFG = {
    "weights": {"relevance": 0.30, "impact": 0.25, "urgency": 0.20, "novelty": 0.15, "source_weight": 0.10},
    "confidence_penalty_threshold": 0.3,
    "confidence_penalty_factor": 0.5,
    "source_weights": {"ASIC Media": 1.0, "default": 0.5},
}


def _classified(id_, source_name="ASIC Media", confidence=0.9, **scores) -> ClassifiedItem:
    defaults = dict(relevance_score=0.8, impact_score=0.7, urgency_score=0.6, novelty_score=0.5)
    defaults.update(scores)
    return ClassifiedItem(
        id=id_, url="https://x.com", canonical_url="https://x.com", title="T", body="",
        source_name=source_name, source_type="news", region="AU",
        published_at=NOW, fetched_at=NOW, raw_metadata={},
        domain="policy", signal_type="regulatory_change",
        confidence=confidence, tags=[], rationale="", **defaults,
    )


def test_score_assigns_rank():
    items = [_classified("a"), _classified("b", relevance_score=0.3)]
    scored = score_items(items, CFG)
    assert scored[0].rank == 1
    assert scored[1].rank == 2
    assert scored[0].strategic_score >= scored[1].strategic_score


def test_score_breakdown_present():
    scored = score_items([_classified("a")], CFG)
    bd = scored[0].score_breakdown
    assert "relevance" in bd
    assert "confidence_penalty" in bd


def test_confidence_penalty_applied():
    low_conf = _classified("a", confidence=0.1)
    high_conf = _classified("b", confidence=0.9)
    scored = score_items([low_conf, high_conf], CFG)
    low = next(s for s in scored if s.id == "a")
    high = next(s for s in scored if s.id == "b")
    assert low.score_breakdown["confidence_penalty"] > 0
    assert high.score_breakdown["confidence_penalty"] == 0


def test_unknown_source_uses_default_weight():
    item = _classified("a", source_name="Unknown Blog")
    scored = score_items([item], CFG)
    assert scored[0].score_breakdown["source_weight"] == CFG["weights"]["source_weight"] * 0.5
