"""Tests for v1b run-metrics computation and the report reader."""
from datetime import datetime, timezone

from csc.pipeline.run_metrics import compute
from csc.pipeline.verify import count_official_released
from csc.schemas.items import ClassifiedItem, FilteredItem, RawItem
from csc.tools.run_metrics_report import format_report, load_run_logs

NOW = datetime.now(timezone.utc)


def _raw(tier, **o):
    base = dict(id="r", url="u", canonical_url="u", title="t", body="b",
                source_name="S", source_type="news", trust_tier=tier, region="AU",
                published_at=NOW, fetched_at=NOW, raw_metadata={})
    base.update(o)
    return RawItem(**base)


def _filtered(tier, **o):
    base = dict(id="f", url="u", canonical_url="u", title="t", body="b",
                source_name="S", source_type="news", trust_tier=tier, region="AU",
                published_at=NOW, fetched_at=NOW, raw_metadata={})
    base.update(o)
    return FilteredItem(**base)


def _classified(**o):
    base = dict(id="c", url="u", canonical_url="u", title="t", body="b",
                source_name="S", source_type="news", trust_tier="official", region="AU",
                published_at=NOW, fetched_at=NOW, raw_metadata={})
    base.update(o)
    return ClassifiedItem(**base)


def test_compute_publisher_fetch_and_filter_drop():
    raw = [_raw("trade_press", id="p1"), _raw("trade_press", id="p2"), _raw("official", id="o1")]
    kept = [_filtered("trade_press", id="p1")]  # one publisher dropped, one kept
    m = compute(raw=raw, filtered_kept=kept, labelled=[], held=[], passed=[],
                dedup_stats={}, high_impact_threshold=0.8)
    assert m["publisher_fetched"] == 2
    assert m["publisher_dropped_filter"] == 1


def test_compute_enrich_health():
    labelled = [
        _filtered("trade_press", id="a", enrichment_status="success", evidence_level="full_body"),
        _filtered("trade_press", id="b", enrichment_status="success", evidence_level="excerpt"),
        _filtered("trade_press", id="c", enrichment_status="failed", evidence_level="headline_only"),
        _filtered("official", id="d", enrichment_status="success"),  # not publisher — ignored
    ]
    m = compute(raw=[], filtered_kept=[], labelled=labelled, held=[], passed=[],
                dedup_stats={}, high_impact_threshold=0.8)
    assert m["enrich_attempted"] == 3
    assert m["enrich_success"] == 2
    assert m["enrich_failed"] == 1
    assert m["enrich_excerpt"] == 1


def test_compute_gate_and_phase_metrics():
    held = [_classified(human_review_reason="sensitive_domain, headline_only_high_impact")]
    passed = [_classified(evidence_category="official", evidence_level="full_body",
                          duplicate_count=0, impact_score=0.9)]
    m = compute(raw=[], filtered_kept=[], labelled=[], held=held, passed=passed,
                dedup_stats={"publisher_over_aggregator": 2}, high_impact_threshold=0.8)
    assert m["held_headline_only_high_impact"] == 1
    assert m["official_released"] == 1
    assert m["dedup_publisher_over_aggregator"] == 2


def test_count_official_released_helper():
    items = [
        _classified(evidence_category="official", evidence_level="full_body", duplicate_count=0, impact_score=0.9),
        _classified(evidence_category="official", evidence_level="excerpt", duplicate_count=0, impact_score=0.9),  # not full_body
        _classified(evidence_category="publisher", evidence_level="full_body", duplicate_count=0, impact_score=0.9),  # not official
    ]
    assert count_official_released(items, 0.8) == 1


def test_report_reader(tmp_path):
    import json
    (tmp_path / "run1.jsonl").write_text(json.dumps({
        "run_id": "aaaaaaaa-1", "started_at": "2026-06-27T07:00:00",
        "metrics": {"publisher_fetched": 30, "enrich_success": 28, "official_released": 3},
    }))
    (tmp_path / "run2.jsonl").write_text(json.dumps({
        "run_id": "bbbbbbbb-2", "started_at": "2026-06-26T07:00:00",
        "metrics": {"publisher_fetched": 29, "enrich_success": 27, "official_released": 2},
    }))
    runs = load_run_logs(str(tmp_path))
    assert [r["run_id"] for r in runs] == ["aaaaaaaa-1", "bbbbbbbb-2"]  # newest first
    out = format_report(runs, limit=20)
    assert "aaaaaaaa" in out and "pub_fetch" in out


def test_report_reader_empty(tmp_path):
    assert "No runs with metrics" in format_report(load_run_logs(str(tmp_path)), 20)
