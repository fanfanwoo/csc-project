"""
Verify gate — labels review reasons and partitions classified items into a
pass stream (→ score → brief) and a hold stream (→ human review queue).

Routing is fully deterministic and lives in code; the LLM does not decide it.

Reliability flags pull an item OUT of the brief into the review queue. The stakes
flag (sensitive_domain) does NOT hold — a well-evidenced sensitive item is surfaced
*with* a flag, not hidden.
"""

from csc.schemas.items import ClassifiedItem
from csc.utils.logging import get_logger

logger = get_logger(__name__)

# Stakes keywords — presence marks an item for human attention but does not hold it.
REVIEW_KEYWORDS = {"regulatory", "legal", "compliance", "lending", "privacy", "liability"}

DEFAULT_HIGH_IMPACT_THRESHOLD = 0.8

# Reasons that move an item from the brief into the review queue. sensitive_domain
# is deliberately absent: it marks, it does not hold.
HOLD_REASONS = {
    "low_confidence",
    "single_source_high_impact",
    "headline_only_high_impact",
}


def verify_items(
    items: list[ClassifiedItem],
    confidence_floor: float,
    high_impact_threshold: float = DEFAULT_HIGH_IMPACT_THRESHOLD,
) -> tuple[list[ClassifiedItem], list[ClassifiedItem]]:
    """Label review reasons and partition into (pass_stream, hold_stream).

    Held items must not reach the scorer; they carry their human_review_flag /
    human_review_reason into the review queue.
    """
    pass_stream: list[ClassifiedItem] = []
    hold_stream: list[ClassifiedItem] = []

    for ci in items:
        reasons = _reasons_for(ci, confidence_floor, high_impact_threshold)
        _set_flag(ci, reasons)
        if any(r in HOLD_REASONS for r in reasons):
            hold_stream.append(ci)
        else:
            pass_stream.append(ci)

    logger.info(
        "verify gate",
        extra={"total": len(items), "passed": len(pass_stream), "held": len(hold_stream)},
    )
    return pass_stream, hold_stream


def apply_review_flags(
    items: list[ClassifiedItem],
    confidence_floor: float,
    high_impact_threshold: float = DEFAULT_HIGH_IMPACT_THRESHOLD,
) -> list[ClassifiedItem]:
    """Label review reasons in place without partitioning. Returns the same list.

    The labelling primitive behind verify_items, kept as a standalone op for callers
    that keep the full stream.
    """
    for ci in items:
        _set_flag(ci, _reasons_for(ci, confidence_floor, high_impact_threshold))
    return items


def _reasons_for(
    ci: ClassifiedItem, confidence_floor: float, high_impact_threshold: float
) -> list[str]:
    text = (ci.title + " " + ci.rationale).lower()
    reasons = []

    if ci.confidence < confidence_floor:
        reasons.append("low_confidence")
    if any(k in text for k in REVIEW_KEYWORDS):
        reasons.append("sensitive_domain")
    if ci.duplicate_count == 0 and ci.impact_score >= high_impact_threshold:
        reasons.append("single_source_high_impact")
    # NOTE: large_inference_leap (inference_note length > 200) was removed after the
    # first live run held 17/20 items on it — the classifier writes 210–447-char
    # notes routinely, so length is a weak proxy for an actual inference leap.
    # Revisit with a relative measure in v1b.
    # A headline-only story (Google News, no fetchable body) cannot become a
    # high-impact top signal on a headline alone — hold it for a human.
    if ci.evidence_level == "headline_only" and ci.impact_score >= high_impact_threshold:
        reasons.append("headline_only_high_impact")

    return reasons


def _set_flag(ci: ClassifiedItem, reasons: list[str]) -> None:
    if reasons:
        ci.human_review_flag = True
        ci.human_review_reason = ", ".join(reasons)
