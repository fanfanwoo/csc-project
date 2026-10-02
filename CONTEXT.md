# CONTEXT

The single living orientation doc for this repo. Read this first. It describes the
system **as it currently is** — keep it current. History lives elsewhere: decisions in
`docs/adr/`, design intent in `docs/architectures/`, session logs in the session
summaries. When this doc and the code disagree, the **code wins** — fix this doc.

_Last updated: 2026-09-27 (scheduler fix, heartbeat, test-data guard)._

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
- **v1b complete and merged to `main`**: Phase 0 (official full-body exemption, ADR-0002) and Phases 1–3 (Australian Broker publisher source + `enrich_fetch` + body-capable dedup, ADR-0003). **232 tests passing.**
- **Scheduler outage 2026-07-04 → 2026-09-27** — fix merged to `main` (PR #12, `8841965`): the daily job fired but crashed at import every day; no brief, no alert. Root cause and the fixes are under **Scheduling** below. First venv run 2026-09-28 07:00 exit 0, brief `7ee36f17…`; heartbeat 12:00 exit 0.
- Australian Broker is Atom; `rss_connector` reads only `<description>`/`<summary>`, so every AB body is empty and 30/30 drop as `no_keyword_match` (dry run 2026-09-27) (still 30/30 with the fix — vocabulary, not only the body). Fix on branch `fix/atom-content`.
- Google News AU items are 34–3583 days old (median 320) and all drop as `stale`, so the aggregator contributes nothing (dry run 2026-09-27, 50/50). Cause not yet investigated.
- Live-validated 2026-06-26: 100 fetched (+30 Australian Broker), publisher item fetched to `full_body` (`enrichment_status=success`) and reached both brief and queue; Phase 0 dropped held to 1. Known: classifier occasionally emits `domain="regulatory"` (not in `VALID_DOMAINS`) → caught as `schema_validation_error`, item dropped — pre-existing, not v1b.

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
- **Report timezone** (`pipeline.yaml` top-level `timezone:`, shipped as `Australia/Sydney`): the calendar *human-facing date labels* are rendered in — the brief's `date_range` and the run-metrics `date` column, via `csc/utils/report_tz.py`. Every stored timestamp stays UTC. Why it exists: a 07:00 Sydney run is 20:00–21:00 the previous day in UTC, so UTC-derived labels called every morning brief yesterday. Unset or unknown falls back to UTC.
- **Storage** (`csc/storage/`): JSONL is the active store (`jsonl_store.py`) — briefs to `data/briefs/{run_id}.md`, review queue to `data/review/{run_id}.jsonl`, run logs to `data/logs/`. `supabase_store.py` exists as an alternative backend.
- **LLM:** Google Gemini `gemini-2.5-flash` via `google-genai` SDK, key `GOOGLE_API_KEY`. Prototyped in AI Studio (same model family).
- **Tests:** pytest, fixture-based. Run with the venv: `.venv/bin/python -m pytest -q` from `chief-signal-cat/`.
- **Test-data guard** (`tests/conftest.py`, autouse): every test gets `jsonl_store._DATA_DIR` pointed at `tmp_path`, and the real `data/` tree is snapshotted (size + mtime) before and after — any added/removed/modified path fails the test with the list. Why: `test_classify_failure_accounting` ran `run_pipeline()` with `save_brief`/`append_run_log` patched but not `append_items`, so fixture items leaked into `data/review/` (2026-06-24 → 06-26) and showed up as fake recurrence in `review_recurrence`. The 7 leaked files were moved (not deleted) to `data/review/_quarantine/`; the tools glob `data/review/*.jsonl` non-recursively, so they're excluded. New tests that touch storage get isolation for free — don't write to `data/` by absolute path.

## Watching across runs (tools)

- **Run metrics** — each run writes `RunLog.metrics` (`csc/pipeline/run_metrics.py`): publisher_fetched/dropped_filter, enrich success/failed/excerpt, held_headline_only_high_impact, official_released, dedup_publisher_over_aggregator. Read newest-first with `python3 -m csc.tools.run_metrics_report`.
- **Corroboration trigger** — `python3 -m csc.tools.review_recurrence` clusters held single-source signals by **exact URL** (never fuzzy title) and flags non-official recurrences. Recurrence is counted in **distinct calendar days** (local date of `fetched_at`), with run count shown alongside — same-day re-runs don't inflate it. Trigger = on-domain non-official signal recurring across days (`--min-days`, default 2).
- **Heartbeat** — `python3 -m csc.tools.check_heartbeat` exits 1 and emails `email.alert_address` when no file in `data/briefs/` is newer than 36h. Independent of the pipeline — stdlib-only, run by `/usr/bin/python3` in launchd — so it catches import-time crashes the scheduler's own alert can't.

## Scheduling

`csc.pipeline.scheduler` runs the pipeline once with retry + failure-alert email.
Daily activation via macOS launchd: `deploy/launchd/` has two plist templates +
`install.sh` / `uninstall.sh` + README. **Not loaded by default** — run
`bash deploy/launchd/install.sh` from `chief-signal-cat/` (re-run safe; uses
`launchctl bootout`/`bootstrap`). Two agents, both currently loaded on the dev Mac:

| Agent | When | Interpreter | Does |
|---|---|---|---|
| `com.chiefsignalcat.daily` | 07:00 local | `chief-signal-cat/.venv/bin/python` | full pipeline; daily Gemini cost + email; laptop must be awake |
| `com.chiefsignalcat.heartbeat` | 12:00 local | `/usr/bin/python3` | `csc.tools.check_heartbeat`: alert if no brief newer than 36h |

Check with `launchctl print gui/$(id -u)/com.chiefsignalcat.daily` — a growing `runs`
count with `last exit code = 1` means it fires but fails; read `logs/csc.scheduler.log`.

**Root cause of the 2026-07-04 → 09-27 outage.** The job was loaded and fired daily
(85 runs), but the plist pinned `/usr/local/bin/python3` (python.org 3.10, universal
binary). Its global `pydantic_core` wheel is **x86_64-only** (installed 2026-05-31).
Runs succeeded through 2026-07-01; after the 2026-07-04 reboot launchd started the
python as **arm64**, and every run died importing `pydantic_core` (`incompatible
architecture`) via `google.genai`. *Why* it ran as x86_64 before the reboot is not
established — the evidence is only the unchanged wheel, the last good run, and the
reboot date. The crash is at *import* time — before `run_once()` — so neither the
retry nor the scheduler's failure-alert ran: 85 silent failures.

**Interpreter decision.** The pipeline runs from the repo venv, not a global python:
`install.sh` picks `$CSC_PYTHON` → `chief-signal-cat/.venv/bin/python` → `python3` on
PATH, and verifies `import csc.pipeline.scheduler` under `arch -arm64` (how launchd
runs it on Apple Silicon) before installing. Why: the venv's wheels are installed for
the interpreter that runs them and are what `pytest` exercises; the global site-packages
is shared, drifts, and can hold wrong-arch wheels. If the venv is rebuilt or moved,
re-run `install.sh` (the generated plist holds absolute paths and is not committed).

**Heartbeat — why a second agent.** The scheduler can only alert on failures it
survives to see. The heartbeat checks the *outcome* (newest mtime in `data/briefs/`)
instead, so it catches import crashes, a job launchd never starts, or a laptop that
slept through the week. It is deliberately **stdlib-only** (no PyYAML/pydantic: it reads
`config/email.yaml` scalars and `.env` itself, sends over `smtplib`) and runs on
`/usr/bin/python3` (override `CSC_HEARTBEAT_PYTHON`), so a broken venv can't take the
alert down with the pipeline. SMTP only (SendGrid isn't implemented anywhere). With a
36h window and a noon check, the first alert fires the day *after* a missed 07:00 run.

## What's next

- **Confirm the first venv-run** (next 07:00 after the fix): `launchctl print` shows `last exit code = 0` and a new brief in `data/briefs/`.
- **Accumulate runs**, then read the two watch
  tools after a batch. Decisions they inform: is Australian Broker delivering on-domain
  car-finance depth (else add a dedicated auto-finance source, body-checked first); is
  enrich reliable.
- **Land `fix/atom-content`**; dry-run before/after drop counts.
- **Filter changes one at a time:** content fix → vocabulary (incl. plurals). Measure between each.
- **Corroboration trigger is not evaluable** until the content fix lands and ~2 weeks of clean daily runs accumulate.
- **Fix deterministic defects before building the evidence-sufficiency loop**, so the loop's `fetch_full_text` isn't masking a connector bug.
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
