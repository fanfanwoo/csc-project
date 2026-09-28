# 4. Per-source keyword allowlists, with plurals written out

- **Status:** Accepted
- **Date:** 2026-09-27
- **Relates to:** ADR-0003 (Australian Broker as a body-capable publisher source) — makes that source's items reach the pipeline at all.
- **Context branch:** `fix/atom-content`

## Context

The filter's `keyword_allowlist` was global: one list in `config/pipeline.yaml`, applied to every source. Its terms are car-finance vocabulary ("car loan", "novated lease", "BNPL", "interest rate", …) chosen for the original sources.

Australian Broker covers a different scope: rates, lending, and credit demand. On 2026-09-27 all 30 of its items were dropped as `no_keyword_match`, both before and after the Atom `<content>` connector fix gave them bodies. Its items say "cash rate hike", "fixed rates", "RBA", "lenders", "home lending", and never "interest rate".

Adding those terms globally would also apply them to Google News AU, an aggregator with a broad query. There, "RBA", "lending" or "borrowing" would admit general rate and property news that the global list deliberately keeps out.

## Decision

1. **A source may carry its own `keyword_allowlist` in `config/sources.yaml`.** An item passes the keyword check if it matches the global list **or** its own source's list. Other sources never see that list. `filter_items(items, cfg, sources)` receives the sources config, and `run.py` passes it.
2. **Matching is unchanged:** `re.escape` plus `\b…\b` whole-word matching, case-insensitive, for both lists. No regex in config and no pattern rules.
3. **Plurals are written out as their own keywords** (`lender`, `lenders`, `rate hike`, `rate hikes`) rather than handled by a plural rule.
4. **Every item records where each match came from**, in `FilteredItem.keyword_matches` as `{"list": "global" | "source:<name>", "term": …}`.

**Why per-source.** Scope differs by source. A trade-press feed about lending needs lending vocabulary. A broad aggregator needs a tight list. One global list forces a choice between starving the specialist source and flooding the aggregator.

**Why explicit plurals over a rule.** The list stays inspectable: what is in the file is exactly what matches. A suffix rule (`s?`, `(?:s|es)?`) would match forms nobody reviewed, such as "RBAs" or "lendings", and would change the global list's behaviour too. That is a second filter change in the same step. The cost is a longer list, which is accepted.

## Consequences

- Australian Broker, 2026-09-27: kept count went from 0/30 to 13/30. Items 2, 4, 5, 12, 15, 16 and 23–30 are kept, and every match comes from `source:Australian Broker`. A fixture test pins this against that day's feed.
- Google News AU is unchanged. Live, 0/50 are kept before and after (all 50 are `stale`). With recency pinned to exercise the keyword step, 26/50 are kept before and after, with identical per-item results.
- `keyword_matches` shows whether an item passed on shared or source vocabulary, so a noisy source list is visible in the data rather than inferred.
- New vocabulary for a source is now a config change scoped to that source. Measure one change at a time (per CONTEXT: content fix, then vocabulary).
- Two lists means two places to look. The global list stays the default, and a source list only *adds* to it; it never removes or overrides global terms.
