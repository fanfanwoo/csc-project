"""
Deduplication stage — two-pass URL then fuzzy-title matching.

Pass 1 (exact URL): items sharing canonical_url (or url when canonical is None) within
the same region are merged. Note: aggregator items always have canonical_url=None and
their redirect URLs are always unique, so Pass 1 only fires for official/primary sources.
Pass 2 (fuzzy title): remaining items with SequenceMatcher ratio >= threshold within
the same region are merged. O(n²) per region — acceptable at Day 1 volumes (<200 items).
rapidfuzz is a drop-in upgrade if throughput becomes a concern.
"""

import logging
from dataclasses import replace
from difflib import SequenceMatcher

from csc.schemas.items import FilteredItem

logger = logging.getLogger("csc.pipeline.deduplicate")


def deduplicate(items: list[FilteredItem], cfg: dict) -> list[FilteredItem]:
    """
    Merge duplicate items. Survivors gain duplicate_count, duplicate_source_names,
    duplicate_item_ids provenance. Removed duplicates do not appear in output.
    Input must be pre-filtered (no dropped items).
    """
    fuzzy_threshold = float(cfg.get("fuzzy_threshold", 0.85))
    dedup_across_regions = bool(cfg.get("dedup_across_regions", False))

    if dedup_across_regions:
        survivors = _run_two_pass(items, fuzzy_threshold)
    else:
        by_region: dict[str, list[FilteredItem]] = {}
        for item in items:
            by_region.setdefault(item.region, []).append(item)

        survivors = []
        for group in by_region.values():
            survivors.extend(_run_two_pass(group, fuzzy_threshold))

    logger.info(
        "dedup complete",
        extra={"input": len(items), "output": len(survivors), "merged": len(items) - len(survivors)},
    )
    return survivors


def _run_two_pass(items: list[FilteredItem], fuzzy_threshold: float) -> list[FilteredItem]:
    survivors = _pass1_exact_url(items)
    survivors = _pass2_fuzzy_title(survivors, fuzzy_threshold)
    return survivors


def _pass1_exact_url(items: list[FilteredItem]) -> list[FilteredItem]:
    """Merge items with identical canonical_url (or url when canonical is None)."""
    seen: dict[str, FilteredItem] = {}
    for item in items:
        key = item.canonical_url or item.url
        if key not in seen:
            seen[key] = item
        else:
            winner, loser = _pick_winner(seen[key], item)
            logger.debug("exact-url merge", extra={"kept": winner.id, "merged": loser.id})
            seen[key] = _merge(winner, loser, "exact_url")
    return list(seen.values())


def _pass2_fuzzy_title(items: list[FilteredItem], threshold: float) -> list[FilteredItem]:
    """Merge items with similar titles (case-insensitive SequenceMatcher ratio >= threshold)."""
    survivors: list[FilteredItem] = []
    merged_ids: set[str] = set()

    for i, candidate in enumerate(items):
        if candidate.id in merged_ids:
            continue

        current = candidate
        for j in range(i + 1, len(items)):
            other = items[j]
            if other.id in merged_ids:
                continue
            score = SequenceMatcher(None, current.title.lower(), other.title.lower()).ratio()
            if score >= threshold:
                winner, loser = _pick_winner(current, other)
                logger.debug(
                    "fuzzy-title merge",
                    extra={"kept": winner.id, "merged": loser.id, "similarity": round(score, 3)},
                )
                merged_ids.add(loser.id)
                if winner.id != current.id:
                    # other became winner — it will appear in the outer loop; skip it there
                    merged_ids.add(other.id)
                current = _merge(winner, loser, "fuzzy_title")

        survivors.append(current)

    return survivors


def _pick_winner(a: FilteredItem, b: FilteredItem) -> tuple[FilteredItem, FilteredItem]:
    """Return (winner, loser). Dated item beats undated; earlier published_at wins."""
    if a.published_at is None and b.published_at is None:
        return a, b
    if a.published_at is None:
        return b, a
    if b.published_at is None:
        return a, b
    return (a, b) if a.published_at <= b.published_at else (b, a)


def _merge(winner: FilteredItem, loser: FilteredItem, method: str) -> FilteredItem:
    """Attach loser's provenance to winner. Returns a new FilteredItem (dataclass is immutable via replace)."""
    # Preserve order, deduplicate methods — dict.fromkeys is order-preserving
    new_methods = list(dict.fromkeys(winner.dedup_methods + [method]))
    return replace(
        winner,
        duplicate_count=winner.duplicate_count + 1 + loser.duplicate_count,
        duplicate_source_names=winner.duplicate_source_names + [loser.source_name] + loser.duplicate_source_names,
        duplicate_item_ids=winner.duplicate_item_ids + [loser.id] + loser.duplicate_item_ids,
        dedup_methods=new_methods,
    )
