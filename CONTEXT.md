# CONTEXT

The single living orientation doc for this repo. Read this first. It describes the
system **as it currently is** — keep it current. History lives elsewhere: decisions in
`docs/adr/`, design intent in `docs/architectures/`, session logs in the session
summaries. When this doc and the code disagree, the **code wins** — fix this doc.

_Last updated: 2026-06-24 (Day 2 v1a)._

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

- **v1a complete** on branch `day2-v1a-verify` (code complete @ `d9b03d8`), **214 tests passing**.
- **Not yet merged** — `main` is at `c902c81`. Next ops: one real end-to-end run, then PR → merge (create-a-merge-commit).
- Day 1 (deterministic MVP) shipped. Day 2 v1a (evidence labelling + verify gate) shipped. **v1b** (a body-bearing publisher source + `enrich_fetch`) is the next build, not started.

## The pipeline

```
scheduler → fetch_sources → filter → deduplicate → evidence_state → classify
          → verify gate ──┬─ pass → score → summarise → email / brief
                          └─ hold → review queue
```

Where each stage lives (all under `chief-signal-cat/csc/`):

| Stage | File | Role |
|---|---|---|
| scheduler | `pipeline/scheduler.py` | trigger only, no business logic |
| fetch | `pipeline/fetch_sources.py` + `connectors/` | fetch raw items; retries; failed-source handling |
| filter | `pipeline/filter_items.py` | deterministic noise removal (allow/block, recency, region, keywords) |
| deduplicate | `pipeline/deduplicate.py` | exact-URL then fuzzy-title merge |
| evidence_state | `pipeline/evidence_state.py` | derive `evidence_category`, label evidence quality. **No fetching in v1a** |
| classify | `pipeline/classify.py` | LLM classification → structured JSON. Pure (no review flags) |
| verify | `pipeline/verify.py` | deterministic gate: partition pass / hold (see ADR 0001) |
| score | `pipeline/score.py` | rule-based strategic ranking (LLM does not set final priority) |
| summarise | `pipeline/summarise.py` | LLM brief; includes the review-queue section |
| output | `pipeline/send_email.py` | email/brief delivery |
| orchestration | `run.py` | wires the stages; held items skip score and persist to the review queue |

## Sources (`config/sources.yaml`)

- **Google News AU** — aggregator, weight 0.5. **Discovery source only**: no fetchable body (raw redirect, headline snippet). Treated as `headline_only`.
- **ASIC Media** — official regulator, weight 1.0. **Evidence anchor**: full bodies via two-stage fetch (`official_page_connector.py`).

(`manual_csv_connector.py` and `rss_connector.py` also exist; ASIC uses `official_page`, Google News uses `rss`.)

## Data contracts (`csc/schemas/`)

Stage dataclasses inherit, so fields added low travel up: `RawItem → FilteredItem →
ClassifiedItem → ScoredItem` (`schemas/items.py`). Brief and run schemas in
`schemas/briefs.py`, `schemas/runs.py`.

Evidence-state fields on `RawItem` (populated by `evidence_state`): `evidence_category`
(`official|publisher|aggregator`, derived from the 6-value `trust_tier` — **never change
that enum**), `evidence_level` (`full_body|excerpt|headline_only`), `evidence_source`,
`enrichment_status`, `enrichment_reason`.

Review routing (verify gate): **reliability flags hold** (`low_confidence`,
`single_source_high_impact`, `headline_only_high_impact`);
**`sensitive_domain` marks but passes**. One shared threshold `verify.high_impact_threshold`
(0.8). (`large_inference_leap` was dropped after the first live run held 17/20 on it —
length is a weak proxy; v1b candidate.) Full rationale in `docs/adr/0001-verify-gate-routing.md`.

## Config, storage, LLM

- **Config** (`chief-signal-cat/config/`): `pipeline.yaml` (processing logic + thresholds), `sources.yaml` (source defs + connector dispatch), `email.yaml` (credentials only).
- **Storage** (`csc/storage/`): JSONL is the active store (`jsonl_store.py`) — briefs to `data/briefs/{run_id}.md`, review queue to `data/review/{run_id}.jsonl`, run logs to `data/logs/`. `supabase_store.py` exists as an alternative backend.
- **LLM:** Google Gemini `gemini-2.5-flash` via `google-genai` SDK, key `GOOGLE_API_KEY`. Prototyped in AI Studio (same model family).
- **Tests:** pytest, fixture-based. `python3 -m pytest -q` (Mac: `python3` / `pip3`).

## What's next

- **v1b:** confirm a publisher RSS (candidate **The Adviser**) actually carries article body before adding it (run the same fetchability check used on Google News), then add `pipeline/enrich_fetch.py` and fill the `evidence_state` publisher branch. Also revisit the ASIC `single_source_high_impact` seam (ADR 0001 → future ADR).
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
