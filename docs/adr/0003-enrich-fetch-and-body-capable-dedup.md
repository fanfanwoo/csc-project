# 3. enrich_fetch is a deterministic module; dedup prefers the body-capable duplicate

- **Status:** Accepted
- **Date:** 2026-06-26
- **Relates to:** ADR-0001 (verify gate, evidence-as-state), ADR-0002 (official exemption). Realises the v1b precondition for a future corroboration agent without building one.
- **Context branch:** `day2-v1b-publisher-evidence` (Day 2 v1b, Phases 2–3)

## Context

v1a established that evidence quality varies by source and must route signals (ADR-0001). But the only full-body source was ASIC; Google News carried no fetchable body. v1b adds the first body-bearing **publisher** source (Australian Broker, `trade_press`) whose feed body is a headline snippet but whose per-entry article URL is real, static, fetchable HTML. Two questions follow: how to fetch those bodies, and how to resolve the same story arriving from both a publisher and an aggregator.

## Decision

### `enrich_fetch` is a deterministic module, not an agent

`csc/pipeline/enrich_fetch.py` runs after dedup, before evidence_state. For publisher-category items it does **one** fetch + parse + fallback along a fully pre-enumerable path: configured `body_selector` → `<article>` `<p>` text → `og:description`. It reuses `connectors.http.fetch_with_retry` (fixed backoff on one URL). Official items are no-ops; aggregator redirect URLs are never fetched.

This earns module status, not agent status: there is no runtime *choice* of next step. It would become an agent only if getting a body became a decision — try canonical → AMP → cache → escalate. v1b has one publisher and one path, so it does not. (Guiding principle: promote to an agent only when a module must choose/loop/escalate.)

**Ownership split.** `enrich_fetch` owns `enrichment_status` / `enrichment_reason` (the fetch provenance). `evidence_state` owns `evidence_category` / `evidence_source` / `evidence_level` and reads the body length `enrich_fetch` produced — it must **not** overwrite the fetch provenance. This keeps "what happened during fetch" and "how we label the evidence" as separate, debuggable facts.

### Dedup prefers the body-*capable* duplicate, not the body-*bearing* one

"Prefer the duplicate with a body" cannot mean the actual body, because `enrich_fetch` runs **after** dedup — at merge time publisher bodies don't exist yet. It means prefer the duplicate that *can* bear a body, which is knowable now from `trust_tier`. So `_pick_winner` ranks by evidence category (`official` > `publisher` > `aggregator`) first, then falls back to the existing date logic on a tie.

Effect: when the same finance story appears in both Google News and Australian Broker in one run, dedup keeps the **publisher** copy; `enrich_fetch` gives it a full body; it no longer trips `headline_only_high_impact`. This is the **deterministic, in-run** resolution of the held-headline case.

### One shared category helper

The `trust_tier → evidence_category` mapping is factored into `csc/utils/evidence.category_for` and called from `evidence_state`, `enrich_fetch`, and `deduplicate`. Single source of truth; everything routes on the three-bucket category, never on the six-value `trust_tier` directly.

## Consequences

- Publisher items reach the classifier with real article bodies; `evidence_state` can label them `full_body` / `excerpt` honestly.
- The in-run duplicate case is solved deterministically. The **cross-run / no-duplicate-present** case — where a held single-source signal needs a *second source fetched* to corroborate it — is explicitly **not** solved here. That is the future corroboration agent's job, triggered only when live runs show the queue repeatedly holding signals a second look would resolve. v1b satisfies its precondition (a second independent, fetchable source); it does not build it.
- Publisher items are filtered on **title only** (filter runs before enrich, bodies are empty then). Accepted per the filter-before-fetch rule; run metrics watch whether it drops too many relevant items before any reorder is considered.
- `body_selector` is a per-source maintenance point in `sources.yaml`, like ASIC's `DETAIL_BODY_ID`. A layout change at the publisher breaks extraction loudly (empty body → `paywalled_or_empty`), not silently.
