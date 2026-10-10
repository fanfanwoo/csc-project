"""
Per-item filter and dedupe decisions — one record per fetched item.

Every item the fetch returned gets exactly one decision line in
data/decisions/{run_id}.jsonl, written at the stage that decided its fate:

  stage "filter", decision "dropped", reason = filter_reason (stale, no_keyword_match, ...)
  stage "dedupe", decision "dropped", reason "duplicate"   (merged into another item)
  stage "dedupe", decision "kept",    reason "kept"        (passed both stages)

Items kept at dedupe get a second line once classify has run, recording what
was fetched for them and whether classification succeeded:

  stage "classify", decision "kept",    reason "classified"
  stage "classify", decision "dropped", reason = the failure's error_type
                                        (api_error, json_parse_error, ...)

The classify line carries the item's evidence after enrichment: what the enrich
fetch did (enrichment_status / enrichment_reason), the evidence level classify
saw, and the body length it had to work with.

Items that were classified get a third line at the verify gate, recording what
the gate saw and what it decided:

  stage "verify", decision "kept", reason "passed"   (goes on to score and the brief)
  stage "verify", decision "held", reason = the review reasons that held it
                                   (low_confidence, single_source_high_impact, ...)

The verify line carries the gate's inputs (confidence, impact_score,
duplicate_count, evidence_category, evidence_level) and the model's other
scores, for passed and held items alike. `review_flags` holds every review
reason set on the item, including ones that mark without holding
(sensitive_domain). Before this line existed, only held items kept their scores
(in data/review/), so a passed item's impact score could not be read back.

The file answers "why didn't item X reach the brief?", "what evidence did
classify have?" and "what did the gate see?" without re-running the pipeline.
Bodies are never stored — only their length.
"""

from collections import Counter

from csc.schemas.items import ClassificationFailure, ClassifiedItem, FilteredItem


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


def classify_decisions(
    labelled: list[FilteredItem],
    classified: list[ClassifiedItem],
    failures: list[ClassificationFailure],
) -> list[dict]:
    """Records for every item that entered classify, with its evidence after enrichment.

    Matched by item id: dedupe merges same-URL items, so ids are unique by now.
    """
    classified_ids = {c.id for c in classified}
    failed = {f.item_id: f for f in failures}

    records = []
    for item in labelled:
        if item.id in classified_ids:
            decision, reason, extra = "kept", "classified", {}
        elif item.id in failed:
            f = failed[item.id]
            decision, reason, extra = "dropped", f.error_type, {"error": f.error_message}
        else:
            decision, reason, extra = "dropped", "not_classified", {}
        records.append(
            _record(
                item, "classify", decision, reason,
                enrichment_status=item.enrichment_status,
                enrichment_reason=item.enrichment_reason,
                evidence_level=item.evidence_level,
                evidence_source=item.evidence_source,
                **extra,
            )
        )
    return records


def verify_decisions(passed: list[ClassifiedItem], held: list[ClassifiedItem]) -> list[dict]:
    """Records for every item the verify gate saw: its inputs, scores and outcome.

    Call after verify_items, which sets human_review_reason on each item.
    """
    records = []
    for decision, items in (("kept", passed), ("held", held)):
        for item in items:
            reason = "passed" if decision == "kept" else (item.human_review_reason or "held")
            records.append(
                _record(
                    item, "verify", decision, reason,
                    review_flags=item.human_review_reason,
                    confidence=item.confidence,
                    impact_score=item.impact_score,
                    relevance_score=item.relevance_score,
                    novelty_score=item.novelty_score,
                    urgency_score=item.urgency_score,
                    duplicate_count=item.duplicate_count,
                    evidence_category=item.evidence_category,
                    evidence_level=item.evidence_level,
                    domain=item.domain,
                    signal_type=item.signal_type,
                )
            )
    return records


def summarise_decisions(records: list[dict]) -> dict:
    """Per-source kept/dropped counts by reason, for the run log.

    Pass the filter/dedupe records only: classify and verify records are extra
    lines for items already counted as kept at dedupe.
    """
    summary: dict[str, dict] = {}
    for r in records:
        s = summary.setdefault(r["source"], {"kept": 0, "dropped": 0, "by_reason": {}})
        s[r["decision"]] += 1
        s["by_reason"][r["reason"]] = s["by_reason"].get(r["reason"], 0) + 1
    return {name: summary[name] for name in sorted(summary)}
