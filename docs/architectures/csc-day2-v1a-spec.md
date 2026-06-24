# CSC Day 2 — v1a build spec: evidence-aware verification gate

> **Status:** design intent, not live state. Recorded 2026-06-24.
> **The code is the source of truth.** This document records the plan and the
> rationale behind it; it will drift as the build proceeds (e.g. the `enrich`
> step was renamed `evidence_state` during the build). Read it as a decision
> record — *why* choices were made — not as a description of current behaviour.

**Scope:** v1a only. Ships decision-useful behaviour on the *existing* two sources (ASIC + Google News). No new connectors, no Google News reverse-engineering, no LangGraph, no state machine. (Those are v1b / deferred — see end.)

**Working dir:** `chief-signal-cat/`
**Branch:** `git switch -c day2-v1a-verify` (preserve a review gate before merge)
**Runtime:** macOS, `python3` / `pip3`

---

## Target pipeline (v1a)

```
Source connector
→ Filter
→ Deduplicate
→ evidence_state        (labels evidence quality — no fetching in v1a)
→ Classify
→ verify gate
   ├─ pass  → Score
   └─ hold  → Human review queue
→ Score
→ Summarise
→ Brief
```

`evidence_state` is named deliberately, NOT `enrich` — in v1a it only labels, it does not fetch. The v1b body-fetching module will be a separate `enrich_fetch`.

---

## Pre-flight (do this first, do not skip)

1. Clone fresh and confirm HEAD is `c902c81`.
2. Run the suite: `python3 -m pytest -q` — confirm **188 passing** before changing anything.
3. If the count differs, stop and report — do not build on an unverified baseline.

---

## Why this shape (context for the agent)

- Google News items carry **no fetchable article body**: `rss_connector.py` sets `canonical_url = None` for aggregators, stores the raw Google News redirect in `url`, and puts only the HTML-stripped RSS `<description>` (a headline snippet) in `body`. Do **not** attempt to fetch or resolve these.
- ASIC items already carry full bodies (`official_page_connector.py`, two-stage fetch).
- Therefore on the current two sources, `evidence_state` does **no fetching** in v1a — it only *labels* evidence quality. Real fetching arrives in v1b (`enrich_fetch`) when a body-bearing publisher source is added. Build `evidence_state` so that capability slots in without rewrite.

---

## Schema change (foundation)

Add evidence-state fields to `RawItem` in `csc/schemas/items.py`. Because the stage dataclasses inherit from `RawItem`, these fields travel through `FilteredItem`, `ClassifiedItem`, and `ScoredItem` automatically.

```python
# Evidence provenance — populated by the evidence_state step, travels with the signal
evidence_category: str = "aggregator"   # "official" | "publisher" | "aggregator"  (derived from trust_tier)
evidence_level: str = "headline_only"   # "full_body" | "excerpt" | "headline_only"
evidence_source: str = "unknown"        # "official_page" | "publisher_rss" | "aggregator_rss"
enrichment_status: str = "skipped"      # "success" | "skipped" | "failed"
enrichment_reason: str | None = None    # e.g. "body_present" | "aggregator_url_not_fetchable" | "parse_failed"
```

Defaults are deliberately the "weakest" values so an un-processed item is never mistaken for strong evidence.

**Do NOT change the existing `trust_tier` enum.** It keeps its six valid values (`official, primary_company, major_news, trade_press, aggregator, social`) — config and tests depend on them. Instead, `evidence_state` *derives* `evidence_category` from `trust_tier`:

```
official                                  → official
primary_company | major_news | trade_press → publisher
aggregator | social                        → aggregator
```

Routing logic keys on the three-bucket `evidence_category`, never on the six-value `trust_tier` directly.

---

## Phase 1 — wiring refactor (zero behaviour change)

**Goal:** move the human-review flag logic into its own step without changing any output.

1. Create `csc/pipeline/verify.py`. Move `_apply_review_flags` (currently `classify.py` lines ~175–192) into it as the public entry point, e.g. `apply_review_flags(items, confidence_floor) -> list[ClassifiedItem]`.
2. Remove the call from inside `classify.py` (classify returns to being pure classification).
3. In `run.py`, call `verify.apply_review_flags(...)` as its own step **after** classify and **before** score. All items still flow through to score exactly as before — this phase only relocates code.

**Acceptance criteria**
- `python3 -m pytest -q` → still **188 passing** (move any flag-logic tests to a `test_verify.py`; do not delete coverage).
- A full run produces a **byte-identical brief** to HEAD for the same fixture input.
- `classify.py` no longer references `human_review` anything.

> Do not start Phase 2 until Phase 1 is green and committed.

---

## Phase 2a — evidence_state (labelling only, no fetching)

Create `csc/pipeline/evidence_state.py`. Runs in `run.py` **after dedup, before classify**. Input/output: `list[FilteredItem] -> list[FilteredItem]` (populating the new evidence fields). First step: derive `evidence_category` from `trust_tier` (mapping above), then apply policy by category:

| evidence_category | evidence_state action (v1a) | evidence_source | evidence_level | enrichment_status | enrichment_reason |
|---|---|---|---|---|---|
| `official` | none needed — body already present | `official_page` | `full_body` | `success` | `body_present` |
| `publisher` | *(no such source in v1a — leave a clear `try-fetch` branch stub for v1b `enrich_fetch`)* | `publisher_rss` | set from body length | `success`/`failed` | `body_found`/`parse_failed` |
| `aggregator` | **skip** — never fetch | `aggregator_rss` | `headline_only` | `skipped` | `aggregator_url_not_fetchable` |

- Treat the Google News `<description>` as `headline_only`, **not** `excerpt` — it's publisher promo text, not article evidence.
- The publisher branch is a **stub** in v1a (no such source exists yet). Write it so v1b only has to fill in the fetch, not restructure the module.

**Acceptance criteria**
- Evidence fields populated correctly for ASIC (`official` / `full_body`) and Google News (`aggregator` / `headline_only` / `skipped`).
- New `test_evidence_state.py` with fixtures for one ASIC item and one Google News item, including the `trust_tier → evidence_category` derivation.
- Still green; brief still byte-identical (nothing routes on these fields yet).

---

## Phase 2b — verify gate routing (the behaviour)

Extend `verify.py` to **partition** classified items instead of only labelling them. Two destinations: **pass → score**, **hold → review queue**. Held items must **not** reach the scorer.

Routing rules (all deterministic, in code — the LLM does not decide this):

**Reliability flags → HOLD (out of Top signals, into review queue):**
- `low_confidence` (existing: `confidence < confidence_floor`)
- `single_source_high_impact` (existing: `duplicate_count == 0 and impact_score >= 0.8`)
- `large_inference_leap` (existing: `inference_note` length > 200)
- **NEW** `headline_only_high_impact`: `evidence_level == "headline_only" and impact_score >= 0.8` — a Google-News-only story cannot become a high-impact top signal on a headline alone.

**Stakes flag → KEEP in pass-stream but MARK visibly (do not hold):**
- `sensitive_domain` (existing keyword set: regulatory/legal/compliance/lending/privacy/liability). A well-evidenced lending/privacy item should be surfaced *with* the flag, not hidden.

**Output:**
- Add a `review_queue` list to the run (held items + their `human_review_reason`).
- `run.py`: only pass-stream items go to `score` → `summarise`.
- Brief gains a **Human review queue** section listing held items with reasons (per the default brief structure's "Human review flags").

**Acceptance criteria**
- `test_verify.py` fixtures cover: a clean ASIC item (passes), a low-confidence item (held), a single-source high-impact item (held), a Google-News headline-only high-impact item (held via the new rule), a sensitive-domain item that is otherwise strong (passes, marked).
- Held items verifiably absent from the scored/Top-signals output and present in the review queue.
- Full suite green.

---

## Two decisions for Fan before/at Phase 2b

1. **Threshold for the new `headline_only` rule** — reuse the existing `impact_score >= 0.8`, or set a separate threshold in `pipeline.yaml`? Spec reuses 0.8 for consistency. Confirm or adjust.
2. **Review-queue persistence** — brief section only (v1a default), or also persist held items to `data/review/{run_id}.jsonl` for later audit? Recommend section-only for v1a; add persistence in v1b if the queue proves useful.

---

## Out of scope (the don't-build list — keep it)

Google News reverse-engineering · JS rendering / Playwright · LangGraph · multi-agent intake · parallel source search · complex source-credibility model · any state machine. No cycle exists in v1a, so none is justified.

## v1b preview (next spec, not now)

Confirm a candidate publisher RSS (e.g. **The Adviser** — strong on-domain for consumer finance) **actually carries article body** before adding it (run the same body-fetchability check we ran on Google News — many feeds ship headline + promo only, which would make it a second aggregator). Then add `csc/pipeline/enrich_fetch.py` and fill in the `evidence_state` publisher branch so fetching does real work, and depth improves. The "retry evidence from a better source" idea lives at **dedup** (prefer the body-bearing duplicate), not as a verify arm.
