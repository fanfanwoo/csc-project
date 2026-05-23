from csc.schemas.items import ClassifiedItem


REQUIRED_CLASSIFICATION_FIELDS = [
    "domain", "signal_type", "relevance_score", "impact_score",
    "urgency_score", "novelty_score", "confidence", "rationale",
]


def validate_classified_item(data: dict) -> list[str]:
    errors = []
    for field in REQUIRED_CLASSIFICATION_FIELDS:
        if field not in data:
            errors.append(f"missing field: {field}")
    for score_field in ["relevance_score", "impact_score", "urgency_score", "novelty_score", "confidence"]:
        val = data.get(score_field)
        if val is not None and not (0.0 <= float(val) <= 1.0):
            errors.append(f"{score_field} out of range: {val}")
    return errors
