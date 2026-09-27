"""
Australian Broker per-source vocabulary, checked against the real feed.

Fixture: the 30 items of the live brokernews.com.au Atom feed on 2026-09-27
(verbatim, BOM included), run through the real connector and the real
config/pipeline.yaml filter + config/sources.yaml. Expected keeps were decided
from the titles/standfirsts before the terms were written — if this fails,
report the mismatch rather than tuning terms to fit.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from csc.config import load_config
from csc.connectors.rss_connector import _parse_rss
from csc.pipeline.filter_items import filter_items

FIXTURE = Path(__file__).parent / "fixtures" / "australian_broker_atom_2026-09-27.xml"

# 1-based positions in the feed that should pass the filter.
EXPECTED_KEPT = {2, 4, 5, 12, 15, 16, 23, 24, 26, 27, 28, 29, 30}


def _filtered():
    cfg = load_config()
    src = next(s for s in cfg["sources"] if s["name"] == "Australian Broker")
    xml = FIXTURE.read_text(encoding="utf-8")
    items = _parse_rss(xml, src["name"], src["type"], src["trust_tier"], src["source_weight"], src["region"])
    # Recency is not under test: pin every item inside max_age_days.
    recent = datetime.now(timezone.utc) - timedelta(days=1)
    for item in items:
        item.published_at = recent
    return filter_items(items, cfg["filter"], cfg["sources"])


def test_fixture_is_todays_30_items():
    result = _filtered()
    assert len(result) == 30
    assert result[0].title.startswith("Spotlight: Janine Wade")
    assert result[29].title == "Big Four Banks unite on RBA September rate hike"


def test_expected_items_kept_all_others_dropped():
    result = _filtered()
    kept = {n for n, i in enumerate(result, 1) if i.filter_status != "dropped"}
    dropped_reasons = {i.filter_reason for n, i in enumerate(result, 1) if n not in kept}
    assert kept == EXPECTED_KEPT, {
        "unexpectedly kept": sorted(kept - EXPECTED_KEPT),
        "unexpectedly dropped": sorted(EXPECTED_KEPT - kept),
    }
    assert dropped_reasons == {"no_keyword_match"}


def test_vocab_does_not_apply_to_other_sources():
    # The same text from Google News must still be judged on the global list only.
    cfg = load_config()
    src = next(s for s in cfg["sources"] if s["name"] == "Australian Broker")
    items = _parse_rss(FIXTURE.read_text(encoding="utf-8"), "Google News AU", "news", "aggregator", 0.5, "AU")
    recent = datetime.now(timezone.utc) - timedelta(days=1)
    for item in items:
        item.published_at = recent
    result = filter_items(items, cfg["filter"], cfg["sources"])
    assert all(i.filter_reason == "no_keyword_match" for i in result)
    assert src.get("keyword_allowlist")
