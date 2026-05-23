"""
Full pipeline integration test using fixture data and mocked external calls
(Anthropic API, SMTP, feedparser).
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime.now(timezone.utc)

MOCK_CLASSIFIER_RESPONSE = {
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

MOCK_BRIEF_TEXT = "# Brief\n\n## One-line readout\nASIC tightens rules.\n\n## Top signals\n1. Signal.\n\n## Watch item\nMonitor.\n\n## Human review flags\nNone."


@pytest.fixture
def mock_anthropic():
    client = MagicMock()
    client.messages.create.side_effect = [
        # classifier calls
        MagicMock(
            content=[MagicMock(text=json.dumps(MOCK_CLASSIFIER_RESPONSE))],
            usage=MagicMock(input_tokens=100, output_tokens=50),
        ),
        MagicMock(
            content=[MagicMock(text=json.dumps(MOCK_CLASSIFIER_RESPONSE))],
            usage=MagicMock(input_tokens=100, output_tokens=50),
        ),
        # summariser call
        MagicMock(content=[MagicMock(text=MOCK_BRIEF_TEXT)]),
    ]
    return client


def test_pipeline_end_to_end(mock_anthropic, tmp_path):
    from csc.pipeline.fetch_sources import fetch_all_sources
    from csc.pipeline.filter_items import filter_items
    from csc.pipeline.deduplicate import deduplicate
    from csc.pipeline.classify import classify_items
    from csc.pipeline.score import score_items
    from csc.pipeline.summarise import summarise

    cfg = {
        "sources": [
            {"name": "ASIC Media", "type": "regulator", "url": "https://asic.gov.au/rss", "region": "AU", "source_weight": 1.0, "max_items": 5}
        ],
        "filter_rules": {
            "target_regions": ["AU"], "max_age_days": 30,
            "domain_allowlist": [], "keyword_blocklist": [], "keyword_allowlist": ["ASIC"],
        },
        "dedup": {"fuzzy_threshold": 0.85, "dedup_across_regions": False},
        "classifier": {"model": "claude-sonnet-4-20250514", "max_body_chars": 2000, "confidence_floor": 0.5, "max_retries": 0},
        "scorer": {
            "weights": {"relevance": 0.30, "impact": 0.25, "urgency": 0.20, "novelty": 0.15, "source_weight": 0.10},
            "confidence_penalty_threshold": 0.3, "confidence_penalty_factor": 0.5,
            "source_weights": {"ASIC Media": 1.0, "default": 0.5},
        },
        "summariser": {"model": "claude-sonnet-4-20250514", "top_n": 5, "audience": "test", "max_output_tokens": 1000},
    }

    mock_feed = MagicMock()
    mock_feed.entries = [
        MagicMock(link="https://asic.gov.au/1", title="ASIC lending update", summary="New rules.", id="e1",
                  published_parsed=(2025, 5, 1, 8, 0, 0, 0, 0, 0)),
        MagicMock(link="https://asic.gov.au/2", title="ASIC consumer credit review", summary="Review announced.", id="e2",
                  published_parsed=(2025, 5, 2, 8, 0, 0, 0, 0, 0)),
    ]

    with (
        patch("csc.connectors.rss_connector.feedparser.parse", return_value=mock_feed),
        patch("csc.pipeline.classify.anthropic.Anthropic", return_value=mock_anthropic),
        patch("csc.pipeline.summarise.anthropic.Anthropic", return_value=mock_anthropic),
    ):
        raw = fetch_all_sources(cfg["sources"])
        filtered = filter_items(raw, cfg["filter_rules"])
        deduped = deduplicate([i for i in filtered if not i.filter_reason], cfg["dedup"])
        classified = classify_items(deduped, cfg["classifier"])
        scored = score_items(classified, cfg["scorer"])
        brief = summarise(scored, cfg["summariser"])

    assert len(raw) == 2
    assert len(scored) > 0
    assert scored[0].rank == 1
    assert brief.markdown_body
    assert brief.one_line_readout
