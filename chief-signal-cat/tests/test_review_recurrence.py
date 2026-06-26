"""Tests for the review-queue recurrence watch tool."""
from csc.tools.review_recurrence import (
    build_clusters,
    normalise_title,
    recurring,
    _held_single_source_items,
)


def _held(title, reason, source="ASIC Media", category="official"):
    return {
        "title": title, "human_review_reason": reason,
        "source_name": source, "evidence_category": category,
    }


def test_normalise_strips_doc_prefix_and_case():
    assert normalise_title("26-132MR ASIC reviews car finance") == "asic reviews car finance"
    assert normalise_title("ASIC  reviews   car finance") == "asic reviews car finance"


def test_recurring_signal_clusters_across_runs():
    # Same story held on a single-source reason in two runs → one cluster, 2 runs.
    runs = {
        "run1": [_held("ASIC reviews car finance commissions", "single_source_high_impact")],
        "run2": [_held("26-140MR ASIC reviews car finance commissions", "single_source_high_impact")],
    }
    clusters = build_clusters(runs)
    candidates = recurring(clusters, min_runs=2)
    assert len(candidates) == 1
    assert candidates[0].run_count == 2
    assert "single_source_high_impact" in candidates[0].reasons


def test_one_off_hold_is_not_recurring():
    runs = {"run1": [_held("A one-time high-impact item", "single_source_high_impact")]}
    clusters = build_clusters(runs)
    assert recurring(clusters, min_runs=2) == []


def test_sensitive_only_and_retired_reasons_excluded():
    # sensitive_domain marks-but-passes; large_inference_leap is retired. Neither is a
    # corroboration reason, so an item held only on those is not counted.
    runs = {
        "r1": [_held("Sensitive lending item", "sensitive_domain")],
        "r2": [_held("Sensitive lending item", "sensitive_domain")],
        "r3": [_held("Old verbose item", "large_inference_leap")],
    }
    clusters = build_clusters(runs)
    assert clusters == []
    assert recurring(clusters, min_runs=2) == []


def test_headline_only_high_impact_is_a_corroboration_reason():
    runs = {
        "r1": [_held("Google headline story", "headline_only_high_impact", "Google News AU")],
        "r2": [_held("Google headline story", "sensitive_domain, headline_only_high_impact", "Google News AU")],
    }
    candidates = recurring(build_clusters(runs), min_runs=2)
    assert len(candidates) == 1
    assert candidates[0].run_count == 2


def test_official_recurrence_is_not_a_corroboration_candidate():
    # ASIC (official) held repeatedly — recurs, but you don't corroborate the
    # regulator; it must NOT be a trigger candidate.
    runs = {
        "r1": [_held("ASIC consumer credit review", "single_source_high_impact", "ASIC Media", "official")],
        "r2": [_held("ASIC consumer credit review", "single_source_high_impact", "ASIC Media", "official")],
    }
    (cluster,) = recurring(build_clusters(runs), min_runs=2)
    assert cluster.run_count == 2
    assert cluster.is_corroboration_candidate is False


def test_non_official_recurrence_is_a_corroboration_candidate():
    runs = {
        "r1": [_held("Lone broker scoop on car finance", "single_source_high_impact",
                     "Australian Broker", "publisher")],
        "r2": [_held("Lone broker scoop on car finance", "single_source_high_impact",
                     "Australian Broker", "publisher")],
    }
    (cluster,) = recurring(build_clusters(runs), min_runs=2)
    assert cluster.is_corroboration_candidate is True


def test_held_single_source_items_filters_file(tmp_path):
    import json
    p = tmp_path / "run.jsonl"
    p.write_text(
        json.dumps(_held("kept", "single_source_high_impact")) + "\n"
        + json.dumps(_held("dropped", "sensitive_domain")) + "\n"
    )
    items = _held_single_source_items(str(p))
    assert len(items) == 1
    assert items[0]["title"] == "kept"
