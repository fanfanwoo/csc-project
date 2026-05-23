import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from csc.pipeline.classify import classify_items
from csc.schemas.items import ClassifiedItem, FilteredItem

NOW = datetime.now(timezone.utc)
CFG = {"model": "claude-sonnet-4-20250514", "max_body_chars": 2000, "confidence_floor": 0.5, "max_retries": 1}

MOCK_RESPONSE_JSON = {
    "domain": "policy",
    "signal_type": "regulatory_change",
    "relevance_score": 0.9,
    "novelty_score": 0.7,
    "impact_score": 0.85,
    "urgency_score": 0.8,
    "confidence": 0.88,
    "tags": ["ASIC", "lending"],
    "rationale": "ASIC guidance directly affects car finance providers.",
    "evidence_quote": "new guidance on responsible lending",
    "inference_note": None,
}


def _filtered_item() -> FilteredItem:
    return FilteredItem(
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


def test_classify_returns_classified_item():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text=json.dumps(MOCK_RESPONSE_JSON))],
        usage=MagicMock(input_tokens=100, output_tokens=50),
    )
    with patch("csc.pipeline.classify.anthropic.Anthropic", return_value=mock_client):
        results = classify_items([_filtered_item()], CFG)

    assert len(results) == 1
    ci = results[0]
    assert isinstance(ci, ClassifiedItem)
    assert ci.domain == "policy"
    assert ci.signal_type == "regulatory_change"
    assert 0.0 <= ci.relevance_score <= 1.0


def test_classify_sets_review_flag_for_sensitive_domain():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text=json.dumps(MOCK_RESPONSE_JSON))],
        usage=MagicMock(input_tokens=100, output_tokens=50),
    )
    with patch("csc.pipeline.classify.anthropic.Anthropic", return_value=mock_client):
        results = classify_items([_filtered_item()], CFG)

    assert results[0].human_review_flag is True


def test_classify_handles_parse_failure():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="not valid json {{")],
        usage=MagicMock(input_tokens=10, output_tokens=5),
    )
    with patch("csc.pipeline.classify.anthropic.Anthropic", return_value=mock_client):
        results = classify_items([_filtered_item()], CFG)

    assert results[0].rationale == "classification_failed"
    assert results[0].human_review_flag is True
