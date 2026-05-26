"""
LLM classification stage — calls Gemini to classify each FilteredItem.

Returns (classified_items, failures). Failures are ClassificationFailure objects,
never fake ClassifiedItem records. Human review flags are applied deterministically
by code after classification, not requested from the LLM.
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from google import genai
from google.genai import types

from csc.schemas.items import ClassificationFailure, ClassifiedItem, FilteredItem
from csc.utils.logging import get_logger
from csc.utils.text_cleaning import clean_body
from csc.utils.validation import validate_classified_item

logger = get_logger(__name__)

_PROMPT_DIR = Path(__file__).parent.parent / "prompts"


def classify_items(
    items: list[FilteredItem], cfg: dict
) -> tuple[list[ClassifiedItem], list[ClassificationFailure]]:
    system_prompt = (_PROMPT_DIR / "classifier_prompt.txt").read_text()
    model = cfg.get("model", "gemini-2.0-flash")
    max_body = cfg.get("max_body_chars", 2000)
    confidence_floor = cfg.get("confidence_floor", 0.5)
    max_retries = cfg.get("max_retries", 1)

    classified: list[ClassifiedItem] = []
    failures: list[ClassificationFailure] = []

    for item in items:
        result = _classify_one(item, system_prompt, model, max_body, max_retries, confidence_floor)
        if isinstance(result, ClassifiedItem):
            classified.append(result)
        else:
            failures.append(result)

    logger.info(
        "classify complete",
        extra={"total": len(items), "classified": len(classified), "failures": len(failures)},
    )
    return classified, failures


def _call_llm(system_prompt: str, user_prompt: str, model: str) -> str:
    """Thin Gemini wrapper. Isolated here so tests can mock it without touching provider internals."""
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    response = client.models.generate_content(
        model=model,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=1024,
        ),
    )
    return response.text


def _classify_one(
    item: FilteredItem,
    system_prompt: str,
    model: str,
    max_body: int,
    max_retries: int,
    confidence_floor: float,
) -> ClassifiedItem | ClassificationFailure:
    user_prompt = _build_user_prompt(item, max_body)
    error_type = "api_error"
    error_message = "unknown"
    attempted_at = datetime.now(timezone.utc)

    for attempt in range(max_retries + 1):
        attempted_at = datetime.now(timezone.utc)
        try:
            raw_json = _call_llm(system_prompt, user_prompt, model)
            data = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            error_type, error_message = "json_parse_error", str(exc)
            if attempt < max_retries:
                time.sleep(1)
                continue
            break
        except Exception as exc:
            error_type, error_message = "api_error", str(exc)
            if attempt < max_retries:
                time.sleep(1)
                continue
            break

        errors = validate_classified_item(data)
        if errors:
            error_type, error_message = "schema_validation_error", "; ".join(errors)
            if attempt < max_retries:
                time.sleep(1)
                continue
            break

        ci = _build_classified_item(item, data)
        ci = _apply_review_flags(ci, confidence_floor)
        logger.info("classified", extra={"id": item.id, "model": model})
        return ci

    logger.error(
        "classification failed",
        extra={"id": item.id, "error_type": error_type, "error": error_message},
    )
    return ClassificationFailure(
        item_id=item.id,
        error_type=error_type,
        error_message=error_message,
        model=model,
        attempted_at=attempted_at,
        retry_count=max_retries,
    )


def _build_user_prompt(item: FilteredItem, max_body: int) -> str:
    body_excerpt = clean_body(item.body, max_body)
    kw_ctx = ", ".join(item.matched_keywords) if item.matched_keywords else "none"

    if item.duplicate_count > 0:
        dup_ctx = (
            f"Count: {item.duplicate_count}\n"
            f"Also reported by: {', '.join(item.duplicate_source_names)}\n"
            f"Detection: {', '.join(item.dedup_methods)}"
        )
    else:
        dup_ctx = "None (single source)"

    return (
        f"Source: {item.source_name} ({item.source_type})\n"
        f"Trust tier: {item.trust_tier}\n"
        f"Region: {item.region}\n"
        f"Published: {item.published_at}\n"
        f"URL: {item.url}\n"
        f"Title: {item.title}\n"
        f"Body:\n{body_excerpt}\n\n"
        f"Matched keywords: {kw_ctx}\n"
        f"Filter status: {item.filter_status}\n\n"
        f"Source corroboration:\n{dup_ctx}"
    )


def _build_classified_item(item: FilteredItem, data: dict) -> ClassifiedItem:
    return ClassifiedItem(
        **vars(item),
        domain=data["domain"],
        signal_type=data["signal_type"],
        relevance_score=_clamp(float(data["relevance_score"])),
        novelty_score=_clamp(float(data["novelty_score"])),
        impact_score=_clamp(float(data["impact_score"])),
        urgency_score=_clamp(float(data["urgency_score"])),
        confidence=_clamp(float(data["confidence"])),
        tags=data.get("tags", []),
        rationale=data["rationale"],
        evidence_quote=data.get("evidence_quote"),
        inference_note=data.get("inference_note"),
        human_review_flag=False,
        human_review_reason=None,
    )


def _clamp(val: float) -> float:
    return max(0.0, min(1.0, val))


def _apply_review_flags(ci: ClassifiedItem, confidence_floor: float) -> ClassifiedItem:
    review_keywords = {"regulatory", "legal", "compliance", "lending", "privacy", "liability"}
    text = (ci.title + " " + ci.rationale).lower()
    reasons = []

    if ci.confidence < confidence_floor:
        reasons.append("low_confidence")
    if any(k in text for k in review_keywords):
        reasons.append("sensitive_domain")
    if ci.duplicate_count == 0 and ci.impact_score >= 0.8:
        reasons.append("single_source_high_impact")
    if ci.inference_note and len(ci.inference_note) > 200:
        reasons.append("large_inference_leap")

    if reasons:
        ci.human_review_flag = True
        ci.human_review_reason = ", ".join(reasons)
    return ci
