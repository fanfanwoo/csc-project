"""
Tests for deduplicate pipeline stage.
No network calls — pure deterministic logic.
"""

from datetime import datetime, timedelta, timezone

from csc.pipeline.deduplicate import deduplicate, _pick_winner, _merge
from csc.schemas.items import FilteredItem

NOW = datetime.now(timezone.utc)
CFG = {"fuzzy_threshold": 0.85, "dedup_across_regions": False}

_UNSET = object()


def _item(
    id_: str = "a",
    url: str = "https://example.com/1",
    title: str = "ASIC tightens car loan rules",
    source_name: str = "ASIC Media",
    region: str = "AU",
    published_at=_UNSET,
    canonical_url=_UNSET,
    trust_tier: str = "official",
) -> FilteredItem:
    return FilteredItem(
        id=id_,
        url=url,
        canonical_url=url if canonical_url is _UNSET else canonical_url,
        title=title,
        body="Some body text.",
        source_name=source_name,
        source_type="regulator",
        trust_tier=trust_tier,
        source_weight=1.0,
        region=region,
        published_at=NOW - timedelta(days=1) if published_at is _UNSET else published_at,
        fetched_at=NOW,
        raw_metadata={},
        filter_status="kept",
    )


# ── Empty / no-op ─────────────────────────────────────────────

def test_empty_input_returns_empty():
    assert deduplicate([], CFG) == []


def test_single_item_returned_unchanged():
    item = _item()
    result = deduplicate([item], CFG)
    assert len(result) == 1
    assert result[0].id == "a"
    assert result[0].duplicate_count == 0


def test_unique_items_all_returned():
    a = _item("a", "https://example.com/1", "ASIC responsible lending update")
    b = _item("b", "https://example.com/2", "EV market growth accelerates in Q1")
    result = deduplicate([a, b], CFG)
    assert len(result) == 2
    assert all(i.duplicate_count == 0 for i in result)


# ── Pass 1: Exact URL ─────────────────────────────────────────

def test_exact_url_merges_duplicates():
    a = _item("a", "https://asic.gov.au/news/1", published_at=NOW - timedelta(days=2))
    b = _item("b", "https://asic.gov.au/news/1", published_at=NOW - timedelta(days=1))
    result = deduplicate([a, b], CFG)
    assert len(result) == 1


def test_exact_url_earlier_date_wins():
    a = _item("a", "https://asic.gov.au/news/1", published_at=NOW - timedelta(days=2))
    b = _item("b", "https://asic.gov.au/news/1", published_at=NOW - timedelta(days=1))
    result = deduplicate([a, b], CFG)
    assert result[0].id == "a"


def test_exact_url_provenance_populated():
    a = _item("a", "https://asic.gov.au/news/1", source_name="ASIC Media", published_at=NOW - timedelta(days=2))
    b = _item("b", "https://asic.gov.au/news/1", source_name="AFR", published_at=NOW - timedelta(days=1))
    result = deduplicate([a, b], CFG)
    assert result[0].duplicate_count == 1
    assert "AFR" in result[0].duplicate_source_names
    assert "b" in result[0].duplicate_item_ids


def test_exact_url_canonical_none_falls_back_to_url():
    # Aggregators have canonical_url=None — fall back to url for dedup key
    a = _item("a", "https://news.google.com/redirect/1", canonical_url=None,
              trust_tier="aggregator", published_at=NOW - timedelta(days=2))
    b = _item("b", "https://news.google.com/redirect/1", canonical_url=None,
              trust_tier="aggregator", published_at=NOW - timedelta(days=1))
    result = deduplicate([a, b], CFG)
    assert len(result) == 1
    assert result[0].id == "a"


def test_exact_url_different_urls_not_merged():
    a = _item("a", "https://asic.gov.au/news/1", title="ASIC responsible lending update")
    b = _item("b", "https://asic.gov.au/news/2", title="EV sales surge in Q1 2026")
    result = deduplicate([a, b], CFG)
    assert len(result) == 2


# ── Pass 1: None date tie-breaking ───────────────────────────

def test_exact_url_dated_beats_undated():
    dated = _item("dated", "https://asic.gov.au/news/1", published_at=NOW - timedelta(days=1))
    undated = _item("undated", "https://asic.gov.au/news/1", published_at=None)
    result = deduplicate([undated, dated], CFG)
    assert result[0].id == "dated"


def test_exact_url_both_undated_first_kept():
    a = _item("a", "https://asic.gov.au/news/1", published_at=None)
    b = _item("b", "https://asic.gov.au/news/1", published_at=None)
    result = deduplicate([a, b], CFG)
    assert result[0].id == "a"


# ── Pass 2: Fuzzy title ───────────────────────────────────────

def test_fuzzy_title_merges_similar():
    a = _item("a", "https://example.com/1", "ASIC tightens car loan rules in Australia")
    b = _item("b", "https://example.com/2", "ASIC tightens car loan rules in Australia today")
    result = deduplicate([a, b], CFG)
    assert len(result) == 1


def test_fuzzy_title_earlier_date_wins():
    a = _item("a", "https://example.com/1", "ASIC tightens car loan rules in Australia",
              published_at=NOW - timedelta(days=2))
    b = _item("b", "https://example.com/2", "ASIC tightens car loan rules in Australia today",
              published_at=NOW - timedelta(days=1))
    result = deduplicate([a, b], CFG)
    assert result[0].id == "a"


def test_fuzzy_title_provenance_populated():
    a = _item("a", "https://afr.com/1", "ASIC tightens car loan rules in Australia",
              source_name="AFR", published_at=NOW - timedelta(days=2))
    b = _item("b", "https://abc.com/1", "ASIC tightens car loan rules in Australia today",
              source_name="ABC News", published_at=NOW - timedelta(days=1))
    result = deduplicate([a, b], CFG)
    assert result[0].duplicate_count == 1
    assert "ABC News" in result[0].duplicate_source_names
    assert "b" in result[0].duplicate_item_ids


def test_fuzzy_title_below_threshold_not_merged():
    a = _item("a", "https://example.com/1", "ASIC tightens car loan rules")
    b = _item("b", "https://example.com/2", "EV sales surge as BNPL enters auto finance")
    result = deduplicate([a, b], CFG)
    assert len(result) == 2
    assert all(i.duplicate_count == 0 for i in result)


def test_fuzzy_title_case_insensitive():
    a = _item("a", "https://example.com/1", "ASIC TIGHTENS CAR LOAN RULES IN AUSTRALIA")
    b = _item("b", "https://example.com/2", "asic tightens car loan rules in australia")
    result = deduplicate([a, b], CFG)
    assert len(result) == 1


def test_fuzzy_threshold_respected():
    cfg_strict = {**CFG, "fuzzy_threshold": 0.99}
    a = _item("a", "https://example.com/1", "ASIC tightens car loan rules in Australia")
    b = _item("b", "https://example.com/2", "ASIC tightens car loan rules in Australia today")
    result = deduplicate([a, b], cfg_strict)
    assert len(result) == 2


# ── Three-way merge ───────────────────────────────────────────

def test_three_way_merge_one_survivor():
    a = _item("a", "https://afr.com/1", "ASIC tightens car loan rules in Australia",
              source_name="AFR", published_at=NOW - timedelta(days=3))
    b = _item("b", "https://abc.com/1", "ASIC tightens car loan rules in Australia today",
              source_name="ABC", published_at=NOW - timedelta(days=2))
    c = _item("c", "https://smh.com/1", "ASIC tightens car loan rules in Australia now",
              source_name="SMH", published_at=NOW - timedelta(days=1))
    result = deduplicate([a, b, c], CFG)
    assert len(result) == 1
    assert result[0].id == "a"
    assert result[0].duplicate_count == 2


def test_three_way_merge_provenance_complete():
    a = _item("a", "https://afr.com/1", "ASIC tightens car loan rules in Australia",
              source_name="AFR", published_at=NOW - timedelta(days=3))
    b = _item("b", "https://abc.com/1", "ASIC tightens car loan rules in Australia today",
              source_name="ABC", published_at=NOW - timedelta(days=2))
    c = _item("c", "https://smh.com/1", "ASIC tightens car loan rules in Australia now",
              source_name="SMH", published_at=NOW - timedelta(days=1))
    result = deduplicate([a, b, c], CFG)
    assert set(result[0].duplicate_source_names) == {"ABC", "SMH"}
    assert set(result[0].duplicate_item_ids) == {"b", "c"}


# ── Cross-region ──────────────────────────────────────────────

def test_cross_region_not_deduped_by_default():
    au = _item("au", "https://example.com/1", "ASIC tightens car loan rules in Australia", region="AU")
    us = _item("us", "https://example.com/1", "ASIC tightens car loan rules in Australia", region="US")
    result = deduplicate([au, us], CFG)
    assert len(result) == 2


def test_cross_region_deduped_when_enabled():
    cfg_cross = {**CFG, "dedup_across_regions": True}
    au = _item("au", "https://example.com/1", "ASIC tightens car loan rules in Australia", region="AU")
    us = _item("us", "https://example.com/1", "ASIC tightens car loan rules in Australia", region="US")
    result = deduplicate([au, us], cfg_cross)
    assert len(result) == 1


def test_same_region_still_deduped():
    a = _item("a", "https://afr.com/1", "ASIC tightens car loan rules in Australia", region="AU")
    b = _item("b", "https://abc.com/1", "ASIC tightens car loan rules in Australia today", region="AU")
    result = deduplicate([a, b], CFG)
    assert len(result) == 1


# ── Internal helpers ──────────────────────────────────────────

def test_pick_winner_earlier_date_wins():
    a = _item("a", published_at=NOW - timedelta(days=2))
    b = _item("b", published_at=NOW - timedelta(days=1))
    winner, loser = _pick_winner(a, b)
    assert winner.id == "a"
    assert loser.id == "b"


def test_pick_winner_dated_beats_none():
    dated = _item("dated", published_at=NOW - timedelta(days=1))
    undated = _item("undated", published_at=None)
    winner, _ = _pick_winner(undated, dated)
    assert winner.id == "dated"


def test_pick_winner_both_none_first_wins():
    a = _item("a", published_at=None)
    b = _item("b", published_at=None)
    winner, _ = _pick_winner(a, b)
    assert winner.id == "a"


def test_merge_accumulates_provenance():
    winner = _item("w", source_name="AFR")
    loser = _item("l", source_name="ABC")
    merged = _merge(winner, loser, "exact_url")
    assert merged.duplicate_count == 1
    assert "ABC" in merged.duplicate_source_names
    assert "l" in merged.duplicate_item_ids
    assert merged.id == "w"


def test_merge_chains_existing_provenance():
    # Winner already has 1 duplicate; merging another should give count=2
    winner = _item("w", source_name="AFR")
    from dataclasses import replace as dc_replace
    winner = dc_replace(winner, duplicate_count=1, duplicate_source_names=["XYZ"], duplicate_item_ids=["x"])
    loser = _item("l", source_name="ABC")
    merged = _merge(winner, loser, "fuzzy_title")
    assert merged.duplicate_count == 2
    assert set(merged.duplicate_source_names) == {"XYZ", "ABC"}
    assert set(merged.duplicate_item_ids) == {"x", "l"}


# ── Gate criteria: evidence strength preserved ────────────────

def test_exact_canonical_url_merge():
    # Explicit canonical_url match — canonical is set, not falling back to url
    a = _item("a", url="https://news.google.com/redir/1", canonical_url="https://asic.gov.au/news/1",
              published_at=NOW - timedelta(days=2))
    b = _item("b", url="https://news.google.com/redir/2", canonical_url="https://asic.gov.au/news/1",
              published_at=NOW - timedelta(days=1))
    result = deduplicate([a, b], CFG)
    assert len(result) == 1
    assert result[0].duplicate_count == 1


def test_exact_original_url_merge_when_canonical_none():
    # Canonical is None — falls back to url for dedup key
    a = _item("a", url="https://asic.gov.au/news/1", canonical_url=None,
              published_at=NOW - timedelta(days=2))
    b = _item("b", url="https://asic.gov.au/news/1", canonical_url=None,
              published_at=NOW - timedelta(days=1))
    result = deduplicate([a, b], CFG)
    assert len(result) == 1
    assert result[0].id == "a"


def test_normalised_title_whitespace_ignored():
    a = _item("a", url="https://afr.com/1", title="ASIC  tightens  car loan  rules")
    b = _item("b", url="https://abc.com/1", title="ASIC tightens car loan rules")
    # SequenceMatcher handles whitespace differences — should merge above 0.85
    result = deduplicate([a, b], CFG)
    assert len(result) == 1


def test_similar_but_distinct_stories_not_merged():
    # Different enough that they represent genuinely different signals
    a = _item("a", url="https://afr.com/1", title="ASIC launches review of car loan brokers")
    b = _item("b", url="https://abc.com/1", title="CBA reports record profit on home lending")
    result = deduplicate([a, b], CFG)
    assert len(result) == 2
    assert all(i.duplicate_count == 0 for i in result)


def test_dropped_items_not_in_input_contract():
    # Dedup receives only non-dropped items — verify a keep_with_warning item deduplicates normally
    a = _item("a", url="https://asic.gov.au/news/1", title="ASIC tightens car loan rules in Australia",
              published_at=None)
    from dataclasses import replace as dc_replace
    a = dc_replace(a, filter_status="keep_with_warning", filter_reason="missing_published_at")
    b = _item("b", url="https://abc.com/1", title="ASIC tightens car loan rules in Australia today",
              published_at=NOW - timedelta(days=1))
    result = deduplicate([a, b], CFG)
    # dated item wins; keep_with_warning item becomes a duplicate
    assert len(result) == 1
    assert result[0].id == "b"
    assert "a" in result[0].duplicate_item_ids


def test_lead_item_choice_is_deterministic():
    # Same input twice → same result
    items = [
        _item("a", url="https://afr.com/1", title="ASIC tightens car loan rules in Australia",
              published_at=NOW - timedelta(days=2)),
        _item("b", url="https://abc.com/1", title="ASIC tightens car loan rules in Australia today",
              published_at=NOW - timedelta(days=1)),
    ]
    result1 = deduplicate(list(items), CFG)
    result2 = deduplicate(list(items), CFG)
    assert result1[0].id == result2[0].id


def test_output_order_stable():
    # Order of non-merged survivors matches insertion order
    a = _item("a", url="https://afr.com/1", title="ASIC responsible lending crackdown")
    b = _item("b", url="https://abc.com/1", title="EV adoption accelerates in Q1 2026")
    c = _item("c", url="https://smh.com/1", title="BNPL entering motor vehicle finance market")
    result = deduplicate([a, b, c], CFG)
    assert [i.id for i in result] == ["a", "b", "c"]


def test_duplicate_count_correct_two_way():
    a = _item("a", url="https://afr.com/1", title="ASIC tightens car loan rules in Australia",
              published_at=NOW - timedelta(days=2))
    b = _item("b", url="https://abc.com/1", title="ASIC tightens car loan rules in Australia today",
              published_at=NOW - timedelta(days=1))
    result = deduplicate([a, b], CFG)
    assert result[0].duplicate_count == 1


def test_duplicate_source_names_preserved():
    a = _item("a", url="https://afr.com/1", title="ASIC tightens car loan rules in Australia",
              source_name="AFR", published_at=NOW - timedelta(days=2))
    b = _item("b", url="https://abc.com/1", title="ASIC tightens car loan rules in Australia today",
              source_name="ABC News", published_at=NOW - timedelta(days=1))
    result = deduplicate([a, b], CFG)
    assert result[0].duplicate_source_names == ["ABC News"]


def test_duplicate_item_ids_preserved():
    a = _item("a", url="https://afr.com/1", title="ASIC tightens car loan rules in Australia",
              published_at=NOW - timedelta(days=2))
    b = _item("b", url="https://abc.com/1", title="ASIC tightens car loan rules in Australia today",
              published_at=NOW - timedelta(days=1))
    result = deduplicate([a, b], CFG)
    assert result[0].duplicate_item_ids == ["b"]


# ── dedup_methods ─────────────────────────────────────────────

def test_exact_url_merge_populates_exact_url_method():
    a = _item("a", url="https://asic.gov.au/news/1", published_at=NOW - timedelta(days=2))
    b = _item("b", url="https://asic.gov.au/news/1", published_at=NOW - timedelta(days=1))
    result = deduplicate([a, b], CFG)
    assert result[0].dedup_methods == ["exact_url"]


def test_fuzzy_title_merge_populates_fuzzy_title_method():
    a = _item("a", url="https://afr.com/1", title="ASIC tightens car loan rules in Australia",
              published_at=NOW - timedelta(days=2))
    b = _item("b", url="https://abc.com/1", title="ASIC tightens car loan rules in Australia today",
              published_at=NOW - timedelta(days=1))
    result = deduplicate([a, b], CFG)
    assert result[0].dedup_methods == ["fuzzy_title"]


def test_mixed_merges_produce_both_methods_once():
    # a absorbs b via exact_url, then absorbs c via fuzzy_title
    a = _item("a", url="https://asic.gov.au/news/1",
              title="ASIC tightens car loan rules", published_at=NOW - timedelta(days=3))
    b = _item("b", url="https://asic.gov.au/news/1",
              title="Different title entirely", published_at=NOW - timedelta(days=2))
    c = _item("c", url="https://abc.com/1",
              title="ASIC tightens car loan rules today", published_at=NOW - timedelta(days=1))
    result = deduplicate([a, b, c], CFG)
    assert len(result) == 1
    assert set(result[0].dedup_methods) == {"exact_url", "fuzzy_title"}


def test_same_method_appears_once_even_if_used_twice():
    # Two fuzzy-title merges — "fuzzy_title" should appear only once
    a = _item("a", url="https://afr.com/1",
              title="ASIC tightens car loan rules in Australia", published_at=NOW - timedelta(days=3))
    b = _item("b", url="https://abc.com/1",
              title="ASIC tightens car loan rules in Australia today", published_at=NOW - timedelta(days=2))
    c = _item("c", url="https://smh.com/1",
              title="ASIC tightens car loan rules in Australia now", published_at=NOW - timedelta(days=1))
    result = deduplicate([a, b, c], CFG)
    assert result[0].dedup_methods.count("fuzzy_title") == 1


def test_unique_item_has_empty_dedup_methods():
    result = deduplicate([_item()], CFG)
    assert result[0].dedup_methods == []


def test_dedup_methods_stable_across_runs():
    a = _item("a", url="https://asic.gov.au/news/1", published_at=NOW - timedelta(days=2))
    b = _item("b", url="https://asic.gov.au/news/1", published_at=NOW - timedelta(days=1))
    r1 = deduplicate([a, b], CFG)
    r2 = deduplicate([a, b], CFG)
    assert r1[0].dedup_methods == r2[0].dedup_methods
