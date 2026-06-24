"""
Verify stage — applies deterministic human-review flags to classified items.

Relocated from classify.py in Day 2 v1a Phase 1 (wiring refactor, zero behaviour
change): classification stays pure, review-flag policy lives here. The verify gate
(Phase 2b) extends this module to partition items into pass / hold streams.

Flags are applied by code, never requested from the LLM.
"""

from csc.schemas.items import ClassifiedItem
from csc.utils.logging import get_logger

logger = get_logger(__name__)

# Stakes keywords — presence marks an item for human attention regardless of scores.
REVIEW_KEYWORDS = {"regulatory", "legal", "compliance", "lending", "privacy", "liability"}


def apply_review_flags(
    items: list[ClassifiedItem], confidence_floor: float
) -> list[ClassifiedItem]:
    """Mutate each item in place, setting human_review_flag / human_review_reason."""
    for ci in items:
        _apply_one(ci, confidence_floor)
    flagged = sum(1 for ci in items if ci.human_review_flag)
    logger.info("review flags applied", extra={"total": len(items), "flagged": flagged})
    return items


def _apply_one(ci: ClassifiedItem, confidence_floor: float) -> ClassifiedItem:
    text = (ci.title + " " + ci.rationale).lower()
    reasons = []

    if ci.confidence < confidence_floor:
        reasons.append("low_confidence")
    if any(k in text for k in REVIEW_KEYWORDS):
        reasons.append("sensitive_domain")
    if ci.duplicate_count == 0 and ci.impact_score >= 0.8:
        reasons.append("single_source_high_impact")
    if ci.inference_note and len(ci.inference_note) > 200:
        reasons.append("large_inference_leap")

    if reasons:
        ci.human_review_flag = True
        ci.human_review_reason = ", ".join(reasons)
    return ci
