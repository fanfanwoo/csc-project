import json
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from csc.pipeline.classify import classify_items
from csc.schemas.items import ClassificationFailure, ClassifiedItem, FilteredItem

NOW = datetime.now(timezone.utc)
CFG = {"model": "gemini-2.0-flash", "max_body_chars": 2000, "confidence_floor": 0.5, "max_retries": 1}

MOCK_LLM_RESPONSE = {
    "domain": "policy",
    "signal_type": "regulatory_change",
    "relevance_score": 0.9,
    "novelty_score": 0.7,
    "impact_score": 0.85,
    "urgency_score": 0.8,
    "confidence": 0.88,
    "tags": ["ASIC", "lending"],
    "rationale": "New ASIC lending obligations directly affect car finance providers.",
    "evidence_quote": "new guidance on responsible lending",
    "inference_note": None,
}


def _filtered_item(**overrides) -> FilteredItem:
    base = FilteredItem(
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
    )
    return replace(base, **overrides) if overrides else base


# ── Return shape ──────────────────────────────────────────────


def test_classify_returns_tuple():
    with patch("csc.pipeline.classify._call_llm", return_value=json.dumps(MOCK_LLM_RESPONSE)):
        result = classify_items([_filtered_item()], CFG)
    assert isinstance(result, tuple)
    classified, failures = result
    assert isinstance(classified, list)
    assert isinstance(failures, list)


def test_classify_success_path():
    with patch("csc.pipeline.classify._call_llm", return_value=json.dumps(MOCK_LLM_RESPONSE)):
        classified, failures = classify_items([_filtered_item()], CFG)
    assert len(classified) == 1
    assert len(failures) == 0
    ci = classified[0]
    assert isinstance(ci, ClassifiedItem)
    assert ci.domain == "policy"
    assert ci.signal_type == "regulatory_change"
    assert 0.0 <= ci.relevance_score <= 1.0


# ── Failure paths ─────────────────────────────────────────────


def test_classify_parse_error_returns_failure():
    with patch("csc.pipeline.classify._call_llm", return_value="not valid json {{"):
        classified, failures = classify_items([_filtered_item()], CFG)
    assert len(classified) == 0
    assert len(failures) == 1
    assert isinstance(failures[0], ClassificationFailure)
    assert failures[0].error_type == "json_parse_error"
    assert failures[0].item_id == "abc"


def test_classify_api_error_returns_failure():
    with patch("csc.pipeline.classify._call_llm", side_effect=Exception("connection timeout")):
        classified, failures = classify_items([_filtered_item()], CFG)
    assert len(failures) == 1
    assert failures[0].error_type == "api_error"
    assert "connection timeout" in failures[0].error_message


def test_classify_schema_validation_error_returns_failure():
    bad = {**MOCK_LLM_RESPONSE, "domain": "nonexistent_domain"}
    with patch("csc.pipeline.classify._call_llm", return_value=json.dumps(bad)):
        classified, failures = classify_items([_filtered_item()], CFG)
    assert len(failures) == 1
    assert failures[0].error_type == "schema_validation_error"
    assert "invalid domain" in failures[0].error_message


def test_classify_mixed_batch():
    responses = [json.dumps(MOCK_LLM_RESPONSE), "bad json"]
    with patch("csc.pipeline.classify._call_llm", side_effect=responses):
        classified, failures = classify_items(
            [_filtered_item(id="a", url="https://a.com"), _filtered_item(id="b", url="https://b.com")],
            CFG,
        )
    assert len(classified) == 1
    assert len(failures) == 1


def test_classify_failure_has_model_and_retry_count():
    with patch("csc.pipeline.classify._call_llm", return_value="bad json"):
        _, failures = classify_items([_filtered_item()], CFG)
    f = failures[0]
    assert f.model == "gemini-2.0-flash"
    assert f.retry_count == CFG["max_retries"]


# ── Retry logic ───────────────────────────────────────────────


def test_classify_retries_then_succeeds():
    responses = [json.JSONDecodeError("err", "", 0), json.dumps(MOCK_LLM_RESPONSE)]
    with patch("csc.pipeline.classify._call_llm", side_effect=responses):
        classified, failures = classify_items([_filtered_item()], CFG)
    assert len(classified) == 1
    assert len(failures) == 0


def test_classify_exhausts_retries_returns_failure():
    cfg_one_retry = {**CFG, "max_retries": 1}
    with patch("csc.pipeline.classify._call_llm", return_value="bad json"):
        _, failures = classify_items([_filtered_item()], cfg_one_retry)
    assert len(failures) == 1
    assert failures[0].retry_count == 1


# Human-review flag tests moved to test_verify.py (Day 2 v1a Phase 1).
# classify_items no longer applies flags; verify.apply_review_flags does.


# ── User prompt content ───────────────────────────────────────


def test_duplicate_context_in_prompt():
    item = _filtered_item(
        duplicate_count=2,
        duplicate_source_names=["Reuters", "Bloomberg"],
        dedup_methods=["exact_url"],
    )
    captured = {}

    def capture(sys_p, user_p, model):
        captured["prompt"] = user_p
        return json.dumps(MOCK_LLM_RESPONSE)

    with patch("csc.pipeline.classify._call_llm", side_effect=capture):
        classify_items([item], CFG)

    assert "Count: 2" in captured["prompt"]
    assert "Reuters" in captured["prompt"]


def test_matched_keywords_in_prompt():
    item = _filtered_item(matched_keywords=["car loan", "ASIC"])
    captured = {}

    def capture(sys_p, user_p, model):
        captured["prompt"] = user_p
        return json.dumps(MOCK_LLM_RESPONSE)

    with patch("csc.pipeline.classify._call_llm", side_effect=capture):
        classify_items([item], CFG)

    assert "car loan" in captured["prompt"]
    assert "ASIC" in captured["prompt"]


def test_single_source_shows_no_duplicates_in_prompt():
    item = _filtered_item(duplicate_count=0)
    captured = {}

    def capture(sys_p, user_p, model):
        captured["prompt"] = user_p
        return json.dumps(MOCK_LLM_RESPONSE)

    with patch("csc.pipeline.classify._call_llm", side_effect=capture):
        classify_items([item], CFG)

    assert "single source" in captured["prompt"].lower()


def test_excluded_fields_not_in_prompt():
    item = _filtered_item(
        filter_status="kept",
        filter_reason="passed_threshold",
        source_weight=0.8,
        duplicate_item_ids=["item1", "item2"],
        dedup_methods=["exact_url"],
    )
    captured = {}

    def capture(sys_p, user_p, model):
        captured["prompt"] = user_p
        return json.dumps(MOCK_LLM_RESPONSE)

    with patch("csc.pipeline.classify._call_llm", side_effect=capture):
        classify_items([item], CFG)

    prompt = captured["prompt"]
    assert "filter_status" not in prompt.lower()
    assert "filter_reason" not in prompt.lower()
    assert "source_weight" not in prompt.lower()
    assert "duplicate_item_ids" not in prompt.lower()
    assert "dedup_methods" not in prompt.lower()



# ── Score clamping ────────────────────────────────────────────


def test_scores_clamped_to_unit_interval():
    slightly_over = {**MOCK_LLM_RESPONSE, "relevance_score": 1.03, "impact_score": -0.02}
    with patch("csc.pipeline.classify._call_llm", return_value=json.dumps(slightly_over)):
        classified, failures = classify_items([_filtered_item()], CFG)
    assert len(failures) == 0
    assert classified[0].relevance_score == 1.0
    assert classified[0].impact_score == 0.0


def test_wildly_out_of_range_score_returns_failure():
    bad_score = {**MOCK_LLM_RESPONSE, "relevance_score": 7.5}
    with patch("csc.pipeline.classify._call_llm", return_value=json.dumps(bad_score)):
        classified, failures = classify_items([_filtered_item()], CFG)
    assert len(failures) == 1
    assert failures[0].error_type == "schema_validation_error"
