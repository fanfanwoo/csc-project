"""
Filter/dedupe decision records — one JSON line per fetched item in
data/decisions/{run_id}.jsonl (tmp_path via the conftest guard).

Fixture: five items, one per outcome —
  stale            older than max_age_days
  no_keyword_match no allowlist term, strict mode on
  kept             a distinct item that passes everything
  kept + duplicate two sources, same story; the official one wins the merge
"""
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from csc.pipeline.decisions import (
    classify_decisions,
    dedupe_decisions,
    filter_decisions,
    summarise_decisions,
    verify_decisions,
)
from csc.pipeline.deduplicate import deduplicate
from csc.pipeline.filter_items import filter_items
from types import SimpleNamespace

from csc.pipeline.verify import verify_items
from csc.schemas.items import ClassificationFailure, ClassifiedItem, FilteredItem, RawItem
from csc.storage import jsonl_store

NOW = datetime.now(timezone.utc)

FILTER_CFG = {
    "target_regions": ["AU"],
    "max_age_days": 7,
    "keyword_allowlist": ["lending"],
    "require_keyword_match": True,
}
SOURCES = [
    {"name": "ASIC Media", "keyword_allowlist": ["credit"]},
    {"name": "Google News"},
]
DEDUP_CFG = {"fuzzy_threshold": 0.85}


def _item(key: str, title: str, source: str, tier: str, days_ago: float, body: str = "") -> RawItem:
    url = f"https://example.com/{key}"
    return RawItem(
        id=RawItem.generate_id(url), url=url, canonical_url=None,
        title=title, body=body, source_name=source, source_type="news",
        trust_tier=tier, published_at=NOW - timedelta(days=days_ago),
    )


def _fixture() -> list[RawItem]:
    return [
        _item("stale", "Old lending news", "Google News", "aggregator", 30),
        _item("nokw", "Weather update for Sydney", "Google News", "aggregator", 1),
        _item("kept", "ASIC credit licence cancelled", "ASIC Media", "official", 1, body="x" * 120),
        _item("dup-win", "RBA lending rules tightened today", "ASIC Media", "official", 2),
        _item("dup-lose", "RBA lending rules tightened today", "Google News", "aggregator", 1),
    ]


def _decide(raw: list[RawItem]) -> list[dict]:
    filtered_all = filter_items(raw, FILTER_CFG, SOURCES)
    kept = [i for i in filtered_all if i.filter_status != "dropped"]
    return filter_decisions(filtered_all) + dedupe_decisions(kept, deduplicate(kept, DEDUP_CFG))


def _read(data_dir, run_id: str) -> list[dict]:
    path = data_dir / "decisions" / f"{run_id}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_one_line_per_item_with_the_right_reason(isolate_data_dir):
    raw = _fixture()
    jsonl_store.append_decisions("run-1", _decide(raw))

    lines = _read(isolate_data_dir, "run-1")
    assert len(lines) == len(raw)
    by_url = {l["url"].rsplit("/", 1)[1]: l for l in lines}
    assert {k: (v["stage"], v["decision"], v["reason"]) for k, v in by_url.items()} == {
        "stale": ("filter", "dropped", "stale"),
        "nokw": ("filter", "dropped", "no_keyword_match"),
        "kept": ("dedupe", "kept", "kept"),
        "dup-win": ("dedupe", "kept", "kept"),
        "dup-lose": ("dedupe", "dropped", "duplicate"),
    }
    assert by_url["dup-lose"]["duplicate_of"] == by_url["dup-win"]["item_id"]


def test_record_fields_and_no_body(isolate_data_dir):
    raw = _fixture()
    jsonl_store.append_decisions("run-1", _decide(raw))

    rec = next(l for l in _read(isolate_data_dir, "run-1") if l["url"].endswith("/kept"))
    assert rec["item_id"] == raw[2].id
    assert rec["source"] == "ASIC Media"
    assert rec["title"] == "ASIC credit licence cancelled"
    assert rec["published_at"] == raw[2].published_at.isoformat()
    assert rec["fetched_at"] == raw[2].fetched_at.isoformat()
    assert rec["body_length"] == 120
    assert rec["keyword_matches"] == [{"list": "source:ASIC Media", "term": "credit"}]
    assert rec["keyword_lists_matched"] == ["source:ASIC Media"]
    assert "body" not in rec
    assert "x" * 120 not in json.dumps(rec)


def test_append_only(isolate_data_dir):
    records = _decide(_fixture())
    jsonl_store.append_decisions("run-1", records[:2])
    first = (isolate_data_dir / "decisions" / "run-1.jsonl").read_text()
    jsonl_store.append_decisions("run-1", records[2:])

    after = (isolate_data_dir / "decisions" / "run-1.jsonl").read_text()
    assert after.startswith(first)
    assert len(after.splitlines()) == 5


def test_same_url_from_two_sources_is_one_kept_one_duplicate():
    """id is a URL hash, so both items share it — matching must use the source too."""
    a = _item("same", "RBA lending rules", "ASIC Media", "official", 1)
    b = _item("same", "RBA lending rules", "Google News", "aggregator", 1)
    records = _decide([b, a])

    assert sorted((r["source"], r["reason"]) for r in records) == [
        ("ASIC Media", "kept"), ("Google News", "duplicate"),
    ]


def test_summary_counts_per_source_by_reason():
    assert summarise_decisions(_decide(_fixture())) == {
        "ASIC Media": {"kept": 2, "dropped": 0, "by_reason": {"kept": 2}},
        "Google News": {
            "kept": 0, "dropped": 3,
            "by_reason": {"stale": 1, "no_keyword_match": 1, "duplicate": 1},
        },
    }


def test_run_pipeline_writes_decisions_and_summary(isolate_data_dir):
    from csc.run import run_pipeline
    from csc.schemas.briefs import Brief

    cfg = {
        "sources": SOURCES, "filter": FILTER_CFG, "deduplicate": DEDUP_CFG,
        "classification": {}, "scoring": {}, "summary": {}, "email": {},
    }
    brief = Brief(
        run_id="", date_range="2026-10-05", generated_at=NOW,
        one_line_readout="readout", markdown_body="# body",
    )
    with (
        patch("csc.run.load_config", return_value=cfg),
        patch("csc.run.fetch_all_sources", return_value=_fixture()),
        patch("csc.run.assess_sources", return_value=[]),
        patch("csc.run.enrich", side_effect=lambda items, *a: items),
        patch("csc.run.classify_items", return_value=([], [])),
        patch("csc.run.summarise", return_value=brief),
        patch("csc.run.send_email"),
    ):
        log = run_pipeline()

    lines = _read(isolate_data_dir, log.run_id)
    early = [l for l in lines if l["stage"] != "classify"]
    assert sorted(l["reason"] for l in early) == ["duplicate", "kept", "kept", "no_keyword_match", "stale"]
    # The two dedupe survivors get a classify line; the mock classified neither.
    late = [l for l in lines if l["stage"] == "classify"]
    assert sorted(l["url"].rsplit("/", 1)[1] for l in late) == ["dup-win", "kept"]
    assert {l["reason"] for l in late} == {"not_classified"}
    assert log.decisions["Google News"]["by_reason"] == {"stale": 1, "no_keyword_match": 1, "duplicate": 1}

    run_log = json.loads((isolate_data_dir / "logs" / f"{log.run_id}.jsonl").read_text())
    assert run_log["decisions"] == log.decisions


# ── classify stage ────────────────────────────────────────────

def _survivors() -> list[FilteredItem]:
    filtered_all = filter_items(_fixture(), FILTER_CFG, SOURCES)
    kept = [i for i in filtered_all if i.filter_status != "dropped"]
    return deduplicate(kept, DEDUP_CFG)


def test_classify_records_carry_outcome_and_evidence():
    survivors = _survivors()
    ok, bad = survivors
    ok.enrichment_status, ok.enrichment_reason = "skipped", None
    ok.evidence_level, ok.evidence_source = "full_body", "official_page"
    bad.enrichment_status, bad.enrichment_reason = "failed", "fetch_failed"
    bad.evidence_level, bad.evidence_source = "headline_only", "publisher_rss"
    failure = ClassificationFailure(
        item_id=bad.id, error_type="api_error", error_message="API key not valid",
        model="m", attempted_at=NOW, retry_count=1,
    )

    records = classify_decisions(survivors, [SimpleNamespace(id=ok.id)], [failure])

    by_id = {r["item_id"]: r for r in records}
    assert len(records) == 2
    assert {k: by_id[ok.id][k] for k in ("stage", "decision", "reason", "evidence_level", "body_length")} == {
        "stage": "classify", "decision": "kept", "reason": "classified",
        "evidence_level": "full_body", "body_length": len(ok.body),
    }
    assert {k: by_id[bad.id][k] for k in ("decision", "reason", "error", "enrichment_reason", "evidence_level")} == {
        "decision": "dropped", "reason": "api_error", "error": "API key not valid",
        "enrichment_reason": "fetch_failed", "evidence_level": "headline_only",
    }
    assert all("body" not in r for r in records)


# ── verify stage ──────────────────────────────────────────────

def _classified(item: FilteredItem, *, impact: float, confidence: float = 0.8, **over) -> ClassifiedItem:
    fields = {**asdict(item), "impact_score": impact, "confidence": confidence, "rationale": "Rates moved.", **over}
    return ClassifiedItem(**fields)


def test_verify_records_carry_gate_inputs_for_passed_and_held():
    first, second = _survivors()
    plain = {"title": "Bank changes its fixed rates", "duplicate_count": 0, "evidence_level": "full_body"}
    held_one = _classified(first, impact=0.8, evidence_category="publisher", id="on-the-line", **plain)
    passed_one = _classified(first, impact=0.7, evidence_category="publisher", id="below-line", **plain)
    flagged = _classified(
        second, impact=0.9, evidence_category="official", id="official",
        **{**plain, "title": "Regulator acts"}, rationale="A regulatory change.",
    )

    passed, held = verify_items([held_one, passed_one, flagged], confidence_floor=0.5, high_impact_threshold=0.8)
    records = verify_decisions(passed, held)

    by_id = {r["item_id"]: r for r in records}
    assert len(records) == 3 and {r["stage"] for r in records} == {"verify"}
    # Same article, same evidence: only the impact score decides held vs passed.
    assert {k: by_id["on-the-line"][k] for k in ("decision", "reason", "impact_score", "duplicate_count")} == {
        "decision": "held", "reason": "single_source_high_impact", "impact_score": 0.8, "duplicate_count": 0,
    }
    assert {k: by_id["below-line"][k] for k in ("decision", "reason", "impact_score", "review_flags")} == {
        "decision": "kept", "reason": "passed", "impact_score": 0.7, "review_flags": None,
    }
    # sensitive_domain marks but does not hold: the flag is recorded on a passed line.
    assert {k: by_id["official"][k] for k in ("decision", "reason", "review_flags", "evidence_category")} == {
        "decision": "kept", "reason": "passed", "review_flags": "sensitive_domain", "evidence_category": "official",
    }
    assert all("body" not in r and "confidence" in r for r in records)


def test_run_pipeline_writes_a_verify_line_per_classified_item(isolate_data_dir):
    from csc.run import run_pipeline
    from csc.schemas.briefs import Brief

    cfg = {
        "sources": SOURCES, "filter": FILTER_CFG, "deduplicate": DEDUP_CFG,
        "classification": {}, "scoring": {}, "summary": {}, "email": {},
    }
    brief = Brief(
        run_id="", date_range="2026-10-05", generated_at=NOW,
        one_line_readout="readout", markdown_body="# body",
    )

    def classify(labelled, _cfg):
        return [_classified(i, impact=0.8 if n == 0 else 0.4, evidence_category="publisher") for n, i in enumerate(labelled)], []

    with (
        patch("csc.run.load_config", return_value=cfg),
        patch("csc.run.fetch_all_sources", return_value=_fixture()),
        patch("csc.run.assess_sources", return_value=[]),
        patch("csc.run.enrich", side_effect=lambda items, *a: items),
        patch("csc.run.classify_items", side_effect=classify),
        patch("csc.run.score_items", return_value=[]),
        patch("csc.run.summarise", return_value=brief),
        patch("csc.run.send_email"),
    ):
        log = run_pipeline()

    gate = [l for l in _read(isolate_data_dir, log.run_id) if l["stage"] == "verify"]
    assert sorted((l["decision"], l["impact_score"]) for l in gate) == [("held", 0.8), ("kept", 0.4)]
    assert log.items_held == 1
    # The summary in the run log still counts each fetched item once.
    assert sum(s["kept"] + s["dropped"] for s in log.decisions.values()) == len(_fixture())
