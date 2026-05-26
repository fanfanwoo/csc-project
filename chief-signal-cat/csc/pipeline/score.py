import statistics

from csc.schemas.items import ClassifiedItem, ScoredItem
from csc.utils.logging import get_logger

logger = get_logger(__name__)


def score_items(items: list[ClassifiedItem], cfg: dict) -> list[ScoredItem]:
    weights = cfg.get("weights", {})
    penalty_threshold = cfg.get("confidence_penalty_threshold", 0.7)
    penalty_factor = cfg.get("confidence_penalty_factor", 0.25)

    scored = []
    for item in items:
        sw = item.source_weight
        penalty = max(0, penalty_threshold - item.confidence) * penalty_factor
        score = (
            weights.get("relevance", 0.30) * item.relevance_score
            + weights.get("impact", 0.25) * item.impact_score
            + weights.get("urgency", 0.20) * item.urgency_score
            + weights.get("novelty", 0.15) * item.novelty_score
            + weights.get("source_weight", 0.10) * sw
            - penalty
        )
        breakdown = {
            "relevance": weights.get("relevance", 0.30) * item.relevance_score,
            "impact": weights.get("impact", 0.25) * item.impact_score,
            "urgency": weights.get("urgency", 0.20) * item.urgency_score,
            "novelty": weights.get("novelty", 0.15) * item.novelty_score,
            "source_weight": weights.get("source_weight", 0.10) * sw,
            "confidence_penalty": penalty,
        }
        scored.append(ScoredItem(**vars(item), strategic_score=score, score_breakdown=breakdown))

    scored.sort(key=lambda x: x.strategic_score, reverse=True)
    for i, item in enumerate(scored):
        item.rank = i + 1

    if scored:
        scores = [s.strategic_score for s in scored]
        logger.info(
            "score distribution",
            extra={"min": round(min(scores), 3), "max": round(max(scores), 3), "mean": round(statistics.mean(scores), 3)},
        )
    return scored
