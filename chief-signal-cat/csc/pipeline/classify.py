import json
import time
from pathlib import Path

import anthropic

from csc.schemas.items import ClassifiedItem, FilteredItem
from csc.utils.logging import get_logger

logger = get_logger(__name__)

_PROMPT_DIR = Path(__file__).parent.parent / "prompts"


def classify_items(items: list[FilteredItem], cfg: dict) -> list[ClassifiedItem]:
    client = anthropic.Anthropic()
    system_prompt = (_PROMPT_DIR / "classifier_prompt.txt").read_text()
    model = cfg.get("model", "claude-sonnet-4-20250514")
    max_body = cfg.get("max_body_chars", 2000)
    confidence_floor = cfg.get("confidence_floor", 0.5)
    max_retries = cfg.get("max_retries", 1)

    classified = []
    for item in items:
        result = _classify_one(item, client, system_prompt, model, max_body, max_retries, confidence_floor)
        classified.append(result)
    return classified


def _classify_one(
    item: FilteredItem,
    client: anthropic.Anthropic,
    system_prompt: str,
    model: str,
    max_body: int,
    max_retries: int,
    confidence_floor: float,
) -> ClassifiedItem:
    body_excerpt = item.body[:max_body]
    user_prompt = (
        f"Source: {item.source_name} ({item.source_type})\n"
        f"Region: {item.region}\n"
        f"Title: {item.title}\n"
        f"Body: {body_excerpt}\n\n"
        "Return a JSON object matching the ClassifiedItem schema."
    )

    for attempt in range(max_retries + 1):
        try:
            t0 = time.monotonic()
            response = client.messages.create(
                model=model,
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            latency = time.monotonic() - t0
            raw_json = response.content[0].text
            data = json.loads(raw_json)

            ci = ClassifiedItem(
                **vars(item),
                domain=data.get("domain", "other"),
                signal_type=data.get("signal_type", "weak_signal"),
                relevance_score=float(data.get("relevance_score", 0.0)),
                novelty_score=float(data.get("novelty_score", 0.0)),
                impact_score=float(data.get("impact_score", 0.0)),
                urgency_score=float(data.get("urgency_score", 0.0)),
                confidence=float(data.get("confidence", 0.0)),
                tags=data.get("tags", []),
                rationale=data.get("rationale", ""),
                evidence_quote=data.get("evidence_quote"),
                inference_note=data.get("inference_note"),
                human_review_flag=False,
                human_review_reason=None,
            )
            ci = _apply_review_flags(ci, confidence_floor)
            logger.info(
                "classified",
                extra={
                    "id": item.id,
                    "model": model,
                    "tokens": response.usage.input_tokens + response.usage.output_tokens,
                    "latency": round(latency, 2),
                },
            )
            return ci
        except (json.JSONDecodeError, KeyError) as exc:
            if attempt < max_retries:
                time.sleep(1)
                continue
            logger.error("classification failed", extra={"id": item.id, "error": str(exc)})
            return ClassifiedItem(**vars(item), rationale="classification_failed", human_review_flag=True, human_review_reason="parse_error")


def _apply_review_flags(ci: ClassifiedItem, confidence_floor: float) -> ClassifiedItem:
    review_keywords = {"regulatory", "legal", "compliance", "lending", "privacy", "liability"}
    text = (ci.title + " " + ci.rationale).lower()
    reasons = []

    if ci.confidence < confidence_floor:
        reasons.append("low_confidence")
    if any(k in text for k in review_keywords):
        reasons.append("sensitive_domain")
    if ci.inference_note and len(ci.inference_note) > 200:
        reasons.append("large_inference_leap")

    if reasons:
        ci.human_review_flag = True
        ci.human_review_reason = ", ".join(reasons)
    return ci
