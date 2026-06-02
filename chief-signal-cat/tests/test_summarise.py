from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from csc.pipeline.summarise import summarise
from csc.schemas.items import ScoredItem

NOW = datetime.now(timezone.utc)
CFG = {
    "model": "gemini-2.0-flash",
    "top_n": 3,
    "audience": "product and finance stakeholders",
    "max_output_tokens": 2000,
}

MOCK_BRIEF = """# Chief Signal Cat Brief — 2025-05-20

## One-line readout
ASIC's new guidance creates immediate compliance obligations for vehicle finance providers.

## Top signals
1. **ASIC tightens responsible lending** — New rules take effect Q2 2025.
   **Why it matters:** Direct compliance risk for auto lending products.
   **Evidence:** ASIC Media, 2025-05-01, https://example.com/1.
   **Confidence:** High — regulator primary source.

## Watch item
Monitor ACCC response to responsible lending changes over next 30 days.

## Human review flags
- abc123: sensitive_domain
"""


def _scored(id_="abc") -> ScoredItem:
    return ScoredItem(
        id=id_, url="https://example.com/1", canonical_url="https://example.com/1",
        title="ASIC tightens responsible lending", body="Regulator update.",
        source_name="ASIC Media", source_type="regulator", region="AU",
        published_at=NOW, fetched_at=NOW, raw_metadata={},
        domain="policy", signal_type="regulatory_change",
        relevance_score=0.9, novelty_score=0.7, impact_score=0.85,
        urgency_score=0.8, confidence=0.9, tags=[], rationale="Direct compliance impact.",
        strategic_score=0.85, score_breakdown={}, rank=1,
    )


def test_summarise_returns_brief():
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = MagicMock(text=MOCK_BRIEF)
    with (
        patch("csc.pipeline.summarise.genai.Client", return_value=mock_client),
        patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key"}),
    ):
        brief = summarise([_scored()], CFG)

    assert brief.markdown_body == MOCK_BRIEF
    assert brief.one_line_readout
    assert "abc" in brief.top_signal_ids


def test_summarise_limits_to_top_n():
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = MagicMock(text=MOCK_BRIEF)
    items = [_scored(str(i)) for i in range(10)]
    with (
        patch("csc.pipeline.summarise.genai.Client", return_value=mock_client),
        patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key"}),
    ):
        brief = summarise(items, CFG)

    assert len(brief.top_signal_ids) <= CFG["top_n"]
