# CONTEXT

The single living orientation doc for this repo. Read this first. It describes the
system **as it currently is** — keep it current. History lives elsewhere: decisions in
`docs/adr/`, design intent in `docs/architectures/`, session logs in the session
summaries. When this doc and the code disagree, the **code wins** — fix this doc.

_Last updated: 2026-06-26 (Day 2 v1b)._

## What CSC is

Chief Signal Cat is an **outward-looking** strategic signal intelligence pipeline: it
turns external market, policy, auto/EV, consumer-finance, competitor, and AI signals
into a decision-ready brief for product / design / strategy. Its inward-looking
counterpart is **CDC** (Chief Discovery Cat: customer feedback, reviews, support
themes). Day 3 unifies them; CSC and CDC are separate today.

Guiding principle: build deterministic modules first; promote a module to an "agent"
only when it must choose the next step, retry, coordinate, parallelise, verify, or
escalate. Don't be agentic for its own sake. (See `CLAUDE.md`.)

## Terminology

Only the terms that genuinely cause confusion — the self-evident stages live in the
pipeline table below.

- **Signal** — the domain concept: a piece of external intelligence that something is changing. The product noun ("top signals", `signal_type`, the name on the tin).
- **Item** — the pipeline data record that carries a *candidate* signal stage to stage (`RawItem → ScoredItem`). Not every item becomes a signal: filtered/dropped items never do; held items are signals whose surface-status is undecided pending review.
- **`trust_tier` vs `evidence_category`** — `trust_tier` is the 6-value source-config label; `evidence_category` is the 3-bucket (`official|publisher|aggregator`) value *derived* from it. Routing keys on the derived category, never on `trust_tier` directly.
- **hold vs mark** — reliability flags *hold* an item (out of the brief, into the review queue); the stakes flag (`sensitive_domain`) *marks* it but lets it pass. This split is what makes verify a router, not a filter. (See ADR 0001.)

## Current state

- Day 1 (deterministic MVP) and Day 2 **v1a** (evidence labelling + verify gate) shipped and **merged to `main`**.
- **v1b** in progress: **Phase 0** (official full-body exemption from `single_source_high_impact`, ADR-0002) **merged to `main`** (`1996770`). **Phases 1–3** (Australian Broker publisher source + `enrich_fetch` + body-capable dedup, ADR-0003) on branch `day2-v1b-publisher-evidence`, **232 tests passing**, PR open.
- Two clean v1a live runs done. After v1b merges: a live run to confirm publisher bodies reach the classifier and the `official_released` / publisher-enrich metrics behave.

## The pipeline

```
scheduler → fetch_sources → filter → deduplicate → enrich_fetch → evidence_state → classify
          → verify gate ──┬─ pass → score → summarise → email / brief
                          └─ hold → review queue
```

Where each stage lives (all under `chief-signal-cat/csc/`):

| Stage | File | Role |
|---|---|---|
| scheduler | `pipeline/scheduler.py` | trigger only, no business logic |
| fetch | `pipeline/fetch_sources.py` + `connectors/` | fetch raw items; retries; failed-source handling |
| filter | `pipeline/filter_items.py` | deterministic noise removal (allow/block, recency, region, keywords) |
| deduplicate | `pipeline/deduplicate.py` | exact-URL then fuzzy-title merge; **prefers the body-capable duplicate** (official > publisher > aggregator), then date (ADR-0003) |
| enrich_fetch | `pipeline/enrich_fetch.py` | **deterministic** fetch of publisher article bodies via per-source `body_selector`; official no-op, aggregator skip. Owns `enrichment_status/reason` (ADR-0003) |
| evidence_state | `pipeline/evidence_state.py` | derive `evidence_category`; label `evidence_level` from the (now possibly enriched) body. Owns `evidence_*`, not `enrichment_*` |
| classify | `pipeline/classify.py` | LLM classification → structured JSON. Pure (no review flags) |
| verify | `pipeline/verify.py` | deterministic gate: partition pass / hold (ADR-0001, ADR-0002) |
| score | `pipeline/score.py` | rule-based strategic ranking (LLM does not set final priority) |
| summarise | `pipeline/summarise.py` | LLM brief; includes the review-queue section |
| output | `pipeline/send_email.py` | email/brief delivery |
| orchestration | `run.py` | wires the stages; held items skip score and persist to the review queue |

`csc/utils/evidence.py` (`category_for`) is the single source of truth for the
`trust_tier → evidence_category` mapping, shared by deduplicate, enrich_fetch, and
evidence_state.

## Sources (`config/sources.yaml`)

- **Google News AU** — aggregator, weight 0.5. **Discovery source only**: no fetchable body (raw redirect, headline snippet). Treated as `headline_only`.
- **ASIC Media** — official regulator, weight 1.0. **Evidence anchor**: full bodies via two-stage fetch (`official_page_connector.py`).
- **Australian Broker** — `trade_press` (→ publisher), weight 0.6 (v1b). Feed body is a headline snippet, but each entry's alternate `<link>` is a real `.aspx` article; `enrich_fetch` fetches it using `body_selector: div.article-detail`. Mortgage/property-heavy, lighter on car finance. `/premium/` paths paywalled.

(`manual_csv_connector.py` also exists; ASIC uses `official_page`, Google News + Australian Broker use `rss`.)

## Data contracts (`csc/schemas/`)

Stage dataclasses inherit, so fields added low travel up: `RawItem → FilteredItem →
ClassifiedItem → ScoredItem` (`schemas/items.py`). Brief and run schemas in
`schemas/briefs.py`, `schemas/runs.py`.

Evidence fields on `RawItem`: `evidence_category` (`official|publisher|aggregator`,
derived from the 6-value `trust_tier` — **never change that enum**), `evidence_level`
(`full_body|excerpt|headline_only`), `evidence_source` — owned by `evidence_state`.
`enrichment_status`, `enrichment_reason` — owned by `enrich_fetch` (the fetch
provenance; `evidence_state` must not overwrite them).

Review routing (verify gate): **reliability flags hold** (`low_confidence`,
`single_source_high_impact`, `headline_only_high_impact`);
**`sensitive_domain` marks but passes**. One shared threshold `verify.high_impact_threshold`
(0.8). **Official + full_body items are exempt from `single_source_high_impact`** (ADR-0002):
strong single-source evidence, surfaced not hidden; official excerpt/headline items are
not exempt. (`large_inference_leap` was dropped in v1a — length is a weak proxy.)
Full rationale in `docs/adr/0001…`, `docs/adr/0002…`.

## Config, storage, LLM

- **Config** (`chief-signal-cat/config/`): `pipeline.yaml` (processing logic + thresholds), `sources.yaml` (source defs + connector dispatch), `email.yaml` (credentials only).
- **Storage** (`csc/storage/`): JSONL is the active store (`jsonl_store.py`) — briefs to `data/briefs/{run_id}.md`, review queue to `data/review/{run_id}.jsonl`, run logs to `data/logs/`. `supabase_store.py` exists as an alternative backend.
- **LLM:** Google Gemini `gemini-2.5-flash` via `google-genai` SDK, key `GOOGLE_API_KEY`. Prototyped in AI Studio (same model family).
- **Tests:** pytest, fixture-based. `python3 -m pytest -q` (Mac: `python3` / `pip3`).

## What's next

- **After v1b merges:** a live run to confirm publisher items reach the classifier with real bodies, and to read the v1b run metrics (Australian Broker fetched/dropped-on-title, publisher enrich success/failed/excerpt, items still held by `headline_only_high_impact`, dedup cases where publisher beat aggregator, official items released by Phase 0). If car-finance depth is thin, add a dedicated auto-finance source (body-check it first).
- **Corroboration agent** (the real Day 2 agentic milestone): v1b satisfies its precondition (a second independent, fetchable source). Build it only when live runs show the queue repeatedly holding single-source signals a second source would resolve — not because v1b made it possible.
- **Relative inference-leap measure** to replace the dropped char-count rule — now unblocked by publisher body data; needs several runs to calibrate.
- **Day 3:** integrate CDC (internal) + CSC (external) into a unified intelligence layer.

## Deferred — don't build (no justification yet)

Google News reverse-engineering · JS rendering / Playwright · LangGraph · multi-agent
intake · parallel source search · complex source-credibility model · any state machine
(none until a loop-back cycle exists).

## Where the docs live

- `CONTEXT.md` (this file) — living current state. Update on change.
- `docs/adr/` — decision records (append-only; the durable "why").
- `docs/architectures/` — design specs (dated intent; will age — don't trust over code).
- Session summaries — per-session logs.
- `CLAUDE.md` — agent/repo conventions.
