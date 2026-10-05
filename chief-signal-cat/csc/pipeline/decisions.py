"""
Per-item filter and dedupe decisions — one record per fetched item.

Every item the fetch returned gets exactly one decision line in
data/decisions/{run_id}.jsonl, written at the stage that decided its fate:

  stage "filter", decision "dropped", reason = filter_reason (stale, no_keyword_match, ...)
  stage "dedupe", decision "dropped", reason "duplicate"   (merged into another item)
  stage "dedupe", decision "kept",    reason "kept"        (passed both stages)

The file answers "why didn't item X reach the brief?" without re-running the
pipeline. Bodies are never stored — only their length.
"""

from collections import Counter

from csc.schemas.items import FilteredItem


def _record(item: FilteredItem, stage: str, decision: str, reason: str, **extra) -> dict:
    return {
        "item_id": item.id,
        "source": item.source_name,
        "title": item.title,
        "url": item.url,
        "published_at": item.published_at,
        "fetched_at": item.fetched_at,
        "body_length": len(item.body or ""),
        "stage": stage,
        "decision": decision,
        "reason": reason,
        "keyword_matches": item.keyword_matches,
        "keyword_lists_matched": sorted({m["list"] for m in item.keyword_matches}),
        **extra,
    }


def filter_decisions(filtered_all: list[FilteredItem]) -> list[dict]:
    """Records for items the filter dropped. Kept items are decided at dedupe."""
    return [
        _record(i, "filter", "dropped", i.filter_reason or "unknown")
        for i in filtered_all
        if i.filter_status == "dropped"
    ]


def dedupe_decisions(filtered_kept: list[FilteredItem], survivors: list[FilteredItem]) -> list[dict]:
    """Records for every item that entered dedupe: survivors kept, the rest duplicates.

    Survivors are matched by (id, source_name), not id alone: id is a hash of the
    URL, so the same URL from two sources gives two items with one id, and only
    the winner's source survives the merge.
    """
    remaining = Counter((s.id, s.source_name) for s in survivors)
    merged_into = {lid: s.id for s in survivors for lid in s.duplicate_item_ids}

    records = []
    for item in filtered_kept:
        key = (item.id, item.source_name)
        if remaining[key] > 0:
            remaining[key] -= 1
            records.append(_record(item, "dedupe", "kept", "kept", filter_warning=item.filter_reason))
        else:
            records.append(
                _record(item, "dedupe", "dropped", "duplicate", duplicate_of=merged_into.get(item.id))
            )
    return records


def summarise_decisions(records: list[dict]) -> dict:
    """Per-source kept/dropped counts by reason, for the run log."""
    summary: dict[str, dict] = {}
    for r in records:
        s = summary.setdefault(r["source"], {"kept": 0, "dropped": 0, "by_reason": {}})
        s[r["decision"]] += 1
        s["by_reason"][r["reason"]] = s["by_reason"].get(r["reason"], 0) + 1
    return {name: summary[name] for name in sorted(summary)}
