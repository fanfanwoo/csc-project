from csc.schemas.items import VALID_DOMAINS, VALID_SIGNAL_TYPES


REQUIRED_CLASSIFICATION_FIELDS = [
    "domain", "signal_type", "relevance_score", "impact_score",
    "urgency_score", "novelty_score", "confidence", "rationale",
]

_SCORE_FIELDS = ["relevance_score", "impact_score", "urgency_score", "novelty_score", "confidence"]


def validate_classified_item(data: dict) -> list[str]:
    errors = []

    for field in REQUIRED_CLASSIFICATION_FIELDS:
        if field not in data:
            errors.append(f"missing field: {field}")

    if "domain" in data and data["domain"] not in VALID_DOMAINS:
        errors.append(f"invalid domain: {data['domain']}")

    if "signal_type" in data and data["signal_type"] not in VALID_SIGNAL_TYPES:
        errors.append(f"invalid signal_type: {data['signal_type']}")

    if "rationale" in data and not isinstance(data.get("rationale"), str):
        errors.append("rationale must be a string")

    if "tags" in data and not isinstance(data.get("tags"), list):
        errors.append("tags must be a list")

    for field in _SCORE_FIELDS:
        val = data.get(field)
        if val is None:
            continue
        try:
            fval = float(val)
        except (TypeError, ValueError):
            errors.append(f"{field} not numeric: {val}")
            continue
        if fval < -0.05 or fval > 1.05:
            errors.append(f"{field} out of range: {val}")

    return errors
