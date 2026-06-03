"""
Guard test: classifier failures must be recorded in RunLog.error_count / RunLog.errors.

Before the fix in csc/run.py, `failures` from classify_items() was silently
discarded, so error_count stayed 0 and errors stayed [] even when items failed.
"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

SAMPLE_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>ASIC Media</title>
    <item>
      <title>ASIC lending update</title>
      <link>https://asic.gov.au/1</link>
      <description>New rules on responsible lending.</description>
      <pubDate>Mon, 01 Jun 2026 08:00:00 GMT</pubDate>
    </item>
    <item>
      <title>ASIC consumer credit review</title>
      <link>https://asic.gov.au/2</link>
      <description>Review of consumer credit announced.</description>
      <pubDate>Tue, 02 Jun 2026 08:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""

VALID_CLASSIFIER_RESPONSE = {
    "domain": "policy",
    "signal_type": "regulatory_change",
    "relevance_score": 0.9,
    "novelty_score": 0.7,
    "impact_score": 0.85,
    "urgency_score": 0.8,
    "confidence": 0.88,
    "tags": ["ASIC"],
    "rationale": "Direct compliance impact.",
    "evidence_quote": "new guidance on responsible lending",
    "inference_note": None,
}

MOCK_BRIEF_TEXT = (
    "# Brief\n\n"
    "## One-line readout\nASIC tightens rules.\n\n"
    "## Top signals\n1. Signal.\n\n"
    "## Watch item\nMonitor ASIC lending guidance.\n\n"
    "## Human review flags\nNone."
)

_MINIMAL_CFG = {
    "sources": [
        {
            "name": "ASIC Media",
            "type": "regulator",
            "trust_tier": "official",
            "connector": "rss",
            "url": "https://asic.gov.au/rss",
            "region": "AU",
            "source_weight": 1.0,
            "max_items": 5,
        }
    ],
    "filter": {
        "target_regions": ["AU"],
        "max_age_days": 30,
        "domain_allowlist": [],
        "require_keyword_match": True,
        "min_keyword_matches": 1,
        "keyword_match_exempt_tiers": ["official"],
        "keyword_blocklist": [],
        "keyword_allowlist": ["ASIC"],
        "missing_published_at_policy": {
            "official": "keep_with_warning",
            "regulator": "keep_with_warning",
            "news": "drop",
            "aggregator": "drop",
            "social": "drop",
            "manual": "keep_with_warning",
        },
    },
    "deduplicate": {"fuzzy_threshold": 0.85, "dedup_across_regions": False},
    "classification": {
        "model": "gemini-2.0-flash",
        "max_body_chars": 2000,
        "confidence_floor": 0.5,
        "max_retries": 0,  # no retry so one bad LLM call = one failure
    },
    "scoring": {
        "weights": {
            "relevance": 0.30,
            "impact": 0.25,
            "urgency": 0.20,
            "novelty": 0.15,
            "source_weight": 0.10,
        },
        "confidence_penalty_threshold": 0.3,
        "confidence_penalty_factor": 0.5,
        "source_weights": {"ASIC Media": 1.0, "default": 0.5},
    },
    "summary": {
        "model": "gemini-2.0-flash",
        "top_n": 5,
        "audience": "test",
        "max_output_tokens": 1000,
    },
    "email": {
        "provider": "smtp",
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "from_address": "csc@example.com",
        "recipients": ["test@example.com"],
        "alert_address": "alert@example.com",
    },
}


def test_classify_failure_recorded_in_run_log():
    """
    When one item fails classification, RunLog must have error_count >= 1
    and a corresponding entry in errors with stage/item_id/error_type/error.
    """
    captured_logs = []

    mock_summarise_client = MagicMock()
    mock_summarise_client.models.generate_content.return_value = MagicMock(
        text=MOCK_BRIEF_TEXT
    )

    with (
        patch("csc.run.load_config", return_value=_MINIMAL_CFG),
        patch(
            "csc.connectors.rss_connector._fetch_with_retry",
            return_value=SAMPLE_RSS_XML,
        ),
        # First item → invalid JSON → json_parse_error failure
        # Second item → valid JSON → ClassifiedItem
        patch(
            "csc.pipeline.classify._call_llm",
            side_effect=["not valid json {{{{", json.dumps(VALID_CLASSIFIER_RESPONSE)],
        ),
        patch(
            "csc.pipeline.summarise.genai.Client",
            return_value=mock_summarise_client,
        ),
        patch("csc.run.send_email"),
        patch("csc.run.save_brief", return_value=Path("/tmp/brief.md")),
        patch(
            "csc.run.append_run_log",
            side_effect=lambda log: captured_logs.append(log),
        ),
        patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key"}),
    ):
        from csc.run import run_pipeline
        run_pipeline()

    assert captured_logs, "append_run_log was never called"
    log = captured_logs[0]

    assert log.error_count >= 1, (
        f"expected error_count >= 1, got {log.error_count} — "
        "classify failures not recorded"
    )
    assert log.errors, "errors list is empty — classify failures not recorded"

    classify_errors = [e for e in log.errors if e.get("stage") == "classify"]
    assert classify_errors, f"no 'classify' stage entry in errors: {log.errors}"

    entry = classify_errors[0]
    assert "item_id" in entry, f"missing 'item_id' in error entry: {entry}"
    assert "error_type" in entry, f"missing 'error_type' in error entry: {entry}"
    assert "error" in entry, f"missing 'error' in error entry: {entry}"
    assert entry["error_type"] == "json_parse_error", (
        f"unexpected error_type: {entry['error_type']}"
    )
