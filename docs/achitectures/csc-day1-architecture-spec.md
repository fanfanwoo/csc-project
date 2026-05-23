# Chief Signal Cat — Day 1 Pipeline Architecture Spec

> **Stage:** Day 1 — Deterministic LLM-powered MVP  
> **Goal:** Prove the signal-to-decision loop end to end  
> **Output:** Lightweight email brief, daily or every 3 days  
> **Scope:** One region (AU), one or two source types, car and consumer finance domain

---

## How to read this document

This is the build blueprint for Day 1. Each section covers one pipeline module in the order data flows through the system. For every module you'll find: what it does, what it takes in, what it produces, the rules it must follow, the config it needs, how to test it, and how it evolves into Day 2.

The core principle throughout: **build deterministic modules first, uplift to agents later.** Every module is a simple function — `process(items: list[X]) -> list[Y]` — that can be tested independently and later wrapped by a Day 2 agent without rewriting internals.

---

## Pipeline overview

```
Scheduler
    │
    ▼
Source connector ──→ list[RawItem]
    │
    ▼
Filter rules ──→ list[FilteredItem]
    │
    ▼
Deduplicate ──→ list[FilteredItem] (deduplicated)
    │
    ▼
LLM classifier ──→ list[ClassifiedItem]
    │
    ▼
Signal scorer ──→ list[ScoredItem]
    │
    ▼
LLM summariser ──→ Markdown brief
    │
    ▼
Email output ──→ Sent email
```

**Deterministic modules** (no LLM): Scheduler, Source connector, Filter rules, Deduplicate, Signal scorer, Email output.

**LLM-powered modules**: LLM classifier, LLM summariser. These are the only two modules that call the Anthropic API.

---

## Data schemas

Every module communicates through typed dataclasses. This is the contract that makes each module independently testable and Day 2-ready.

### RawItem

The base unit. Every source connector must produce these.

| Field | Type | Description |
|---|---|---|
| `id` | `str` | Stable hash of canonical URL or source ID |
| `url` | `str` | Original URL |
| `canonical_url` | `str or None` | Resolved canonical URL if available |
| `title` | `str` | Article/item title |
| `body` | `str` | Full text or meaningful excerpt |
| `source_name` | `str` | Human-readable source name |
| `source_type` | `str` | news, regulator, competitor, report, social, internal-note |
| `region` | `str` | AU, US, EU, global |
| `published_at` | `datetime or None` | When the source published the item |
| `fetched_at` | `datetime` | When CSC fetched the item |
| `raw_metadata` | `dict` | Source-specific fields for future use |

### FilteredItem (extends RawItem)

| Field | Type | Description |
|---|---|---|
| `filter_reason` | `str or None` | None means kept; otherwise the reason code |
| `matched_keywords` | `list[str]` | Keywords from the allowlist that matched |
| `excluded_keywords` | `list[str]` | Keywords from the blocklist that matched (if dropped) |
| `duplicate_count` | `int` | Number of near-duplicate items merged into this one (0 = unique) |
| `duplicate_source_names` | `list[str]` | Source names of merged duplicates |
| `duplicate_item_ids` | `list[str]` | Item IDs of merged duplicates |

The three `duplicate_*` fields are populated by the Deduplicate module. Default to `0` / `[]` until dedup runs. A `duplicate_count > 0` means multiple sources reported the same signal — the classifier and scorer should treat this differently from a single-source item.

### ClassifiedItem (extends FilteredItem)

| Field | Type | Description |
|---|---|---|
| `domain` | `str` | policy, market, auto, finance, AI, competitor, consumer, other |
| `signal_type` | `str` | threat, opportunity, weak_signal, trend, regulatory_change, competitor_move |
| `relevance_score` | `float` | 0.0–1.0 |
| `novelty_score` | `float` | 0.0–1.0 |
| `impact_score` | `float` | 0.0–1.0 |
| `urgency_score` | `float` | 0.0–1.0 |
| `confidence` | `float` | 0.0–1.0, LLM self-assessment only |
| `tags` | `list[str]` | Free-form tags for filtering and watchlist matching |
| `rationale` | `str` | One sentence explaining the classification |
| `evidence_quote` | `str or None` | Short source-supported excerpt or paraphrase |
| `inference_note` | `str or None` | What CSC inferred beyond source facts |
| `human_review_flag` | `bool` | Whether this needs human review |
| `human_review_reason` | `str or None` | Why it was flagged |

### ScoredItem (extends ClassifiedItem)

| Field | Type | Description |
|---|---|---|
| `strategic_score` | `float` | Weighted composite score |
| `score_breakdown` | `dict` | Full breakdown: relevance, impact, urgency, novelty, source_weight, confidence_penalty |
| `rank` | `int or None` | Position after sorting |

### ClassificationFailure

A separate object — not a subclass of ClassifiedItem. Returned when the LLM call fails or JSON parsing fails after retries. Logged to `data/logs/{run_id}_failures.jsonl`. Never reaches the scorer.

| Field | Type | Description |
|---|---|---|
| `item_id` | `str` | ID of the FilteredItem that failed |
| `error_type` | `str` | `json_parse_error`, `api_timeout`, `api_error`, `schema_validation_error` |
| `error_message` | `str` | Full error string |
| `model` | `str` | Model string used at time of failure |
| `attempted_at` | `datetime` | When the attempt was made |
| `retry_count` | `int` | How many retries were attempted |

`classify_items()` returns `list[ClassifiedItem]` (successes only). Failures are written to storage and counted in `RunLog.error_count`. They do not propagate downstream.

---

## Module 1: Scheduler

**Job:** Trigger the pipeline on a cadence.

**Implementation:** Use cron (for deployed environments) or APScheduler (for local dev). The scheduler is dumb — it calls the pipeline entry point and logs the result. No business logic, no conditional skipping.

**Config needed:**
- `schedule_cron`: Cron expression (e.g. `0 7 * * *` for daily at 7am)
- `synthesis_window_days`: How many days of items to include (default: 3)
- `recipients`: Email addresses for the brief

**Logging:** Every trigger logs: timestamp, run_id (UUID), status (started/completed/failed), duration, item counts at each stage.

**Error handling:** On failure, retry once after 5 minutes. If second attempt fails, send an alert email to the configured alert address. Never silently skip a run.

**Day 2 upgrade:** The scheduler dissolves into the LangGraph orchestrator which manages state transitions across all agents. The cron trigger becomes the entry node.

---

## Module 2: Source connector

**Job:** Fetch raw content from external sources and return standardised RawItems.

**Day 1 scope:** One region (AU), one or two source types. Recommended starting sources for Australian car and consumer finance:
- **Option A:** Google News RSS filtered to AU + car finance keywords
- **Option B:** A specific industry news API (e.g. NewsAPI with AU domain filter)
- **Option C:** A regulator RSS feed (e.g. ASIC media releases, ACCC auto industry updates)

Start with one. Add the second only after the first works end to end.

**Implementation pattern:**
```python
def fetch_source(config: SourceConfig) -> list[RawItem]:
    # 1. Fetch from source (RSS parse, API call, etc.)
    # 2. Transform each raw entry into a RawItem
    # 3. Generate stable ID from canonical URL hash
    # 4. Return list of RawItems
```

**Config needed per source:**
- `source_name`: Human-readable name
- `source_type`: news / regulator / competitor / report / social / internal-note
- `trust_tier`: `official` | `primary_company` | `major_news` | `trade_press` | `aggregator` | `social`
- `source_url`: Feed URL or API endpoint
- `api_key`: If needed (stored in env vars, never in config files)
- `region`: Default region for this source
- `max_items_per_fetch`: Cap to prevent runaway fetches (default: 50)
- `source_weight`: Used later by the scorer (0.0–1.0)

**Trust tier reference:**

| Tier | Example | Default weight |
|---|---|---|
| `official` | ASIC, ACCC, Treasury, RBA | 1.0 |
| `primary_company` | OEM, lender, fintech newsroom | 0.85 |
| `major_news` | AFR, ABC, Reuters | 0.75 |
| `trade_press` | Auto / finance industry publications | 0.6 |
| `aggregator` | Google News RSS | 0.5 |
| `social` | LinkedIn, X | 0.3 |

`trust_tier` is a human judgment call set in config — never computed. It informs filter exemptions and downstream review decisions.

**Source priority for Day 1:** Start with `official` (ASIC, ACCC) or `trade_press` feeds before `aggregator`. Official sources have lower volume, higher trust, and cleaner evidence. Add Google News RSS as a discovery layer after the primary source works end to end.

**Rules:**
1. Return typed `RawItem` for every item — never raw dicts
2. Handle retries with exponential backoff (3 attempts, base 2s)
3. Log failed sources: error type, timestamp, source name, HTTP status
4. Store anything source-specific in `raw_metadata` for future enrichment
5. Generate stable IDs: `hashlib.sha256(canonical_url.encode()).hexdigest()[:16]`
6. If `published_at` is missing from the source, set to None (don't guess)

**Day 2 upgrade:** Becomes the Intake agent — fetches from multiple sources in parallel, handles partial source failures gracefully, normalises metadata across different source formats.

---

## Module 3: Filter rules

**Job:** Remove obvious noise using deterministic rules before any LLM calls.

This is where you control costs. Every item that gets filtered here is one fewer LLM classification call. Be aggressive but transparent — every drop must have a logged reason.

**Filter chain (applied in order):**

1. **Region check:** Drop items where `region` doesn't match the configured target regions
2. **Recency check:** Apply `missing_published_at_policy` first (see below), then drop items older than `max_age_days` (default: 7)
3. **Domain allowlist:** If configured, keep only items from allowed domains
4. **Keyword blocklist:** Drop items whose title or body contains blocklist terms
5. **Keyword allowlist (strict):** If `require_keyword_match: true`, drop items with fewer than `min_keyword_matches` allowlist matches — unless the source's `trust_tier` is in `keyword_match_exempt_tiers`
6. **Tag matched keywords:** Populate `matched_keywords` on kept items

**Missing published_at policy:**

When `published_at` is `None`, apply the policy by `source_type` before the recency check:

| Source type | Policy | Reason |
|---|---|---|
| `official` / `regulator` | `keep_with_warning` | Regulators may not timestamp media pages; content is high-trust |
| `news` | `drop` | Undated news items are likely stale or low-quality |
| `aggregator` | `drop` | Missing date in aggregator = likely stale summary |
| `social` | `drop` | Undated social = unverifiable |
| `manual` | `keep_with_warning` | Manually curated items are trusted regardless of date |

`keep_with_warning` means: set `published_at = None`, log a metadata warning, continue. These items skip the recency check (no date to compare).

**Config needed:**
```yaml
filter_rules:
  target_regions: ["AU"]
  max_age_days: 7
  domain_allowlist: []  # empty = allow all
  require_keyword_match: true
  min_keyword_matches: 1
  keyword_match_exempt_tiers: ["official"]
  missing_published_at_policy:
    official: "keep_with_warning"
    regulator: "keep_with_warning"
    news: "drop"
    aggregator: "drop"
    social: "drop"
    manual: "keep_with_warning"
  keyword_blocklist:
    - "sponsored content"
    - "press release template"
    - "advertorial"
  keyword_allowlist:
    - "car loan"
    - "vehicle finance"
    - "BNPL"
    - "consumer credit"
    - "auto lending"
    - "ASIC"
    - "ACCC"
    - "responsible lending"
```

**Rules:**
1. No LLM calls — pure Python logic only
2. Every dropped item gets a `filter_reason` code: `off_region`, `stale`, `missing_date`, `blocked_domain`, `blocked_keyword`, `no_keyword_match`
3. Log all drops to the append-only signal log
4. Kept items get `filter_reason = None` and `matched_keywords` populated
5. Config lives in a YAML/JSON file, never hardcoded
6. `keyword_match_exempt_tiers` items pass step 5 automatically — still tagged with `matched_keywords` if any match

**Day 2 upgrade:** Merges with Deduplicate into the Normalisation/enrichment agent which adds entity extraction, source credibility scoring, and geographic enrichment.

---

## Module 4: Deduplicate

**Job:** Remove near-duplicate stories so the classifier doesn't waste tokens on the same news reported by multiple outlets.

**Two-pass approach:**

**Pass 1 — Exact URL match:** If two items share the same `canonical_url` (or `url` if canonical isn't available), keep the one with the earliest `published_at`.

**Pass 2 — Fuzzy title match:** For remaining items, compare titles using `difflib.SequenceMatcher` or `rapidfuzz`. If similarity ratio exceeds the threshold (default: 0.85), merge and keep the earlier item.

**Provenance preservation:**

When items are merged, do not discard the duplicate evidence. The kept item's `FilteredItem` fields are updated:

```python
kept.duplicate_count = len(merged_items)
kept.duplicate_source_names = [i.source_name for i in merged_items]
kept.duplicate_item_ids = [i.id for i in merged_items]
```

This matters downstream: a signal reported by three credible sources should carry more weight than the same signal from one source. The classifier and scorer can read `duplicate_count` directly.

**Rules:**
1. Don't deduplicate across different regions — same story from AU news vs US news may have different regional implications
2. When merging, keep the item with the earliest `published_at`
3. Log which items were merged: original IDs, merge reason, similarity score
4. The output list contains only unique FilteredItems (with provenance fields populated)
5. Run dedup after filtering to avoid comparing items that were already dropped

**Config needed:**
- `fuzzy_threshold`: Similarity ratio cutoff (default: 0.85)
- `dedup_across_regions`: Boolean (default: false)

**Day 2 upgrade:** Part of the Normalisation/enrichment agent. Gains entity-based deduplication (same event, different headline) and cross-source merging with provenance tracking.

---

## Module 5: LLM classifier

**Job:** The first LLM step. Takes each filtered, deduplicated item and returns structured classification.

This is the heart of the intelligence pipeline. The classifier determines domain, signal type, scores, confidence, and whether human review is needed. Its output quality determines brief quality.

**Implementation pattern:**
```python
def classify_items(items: list[FilteredItem], config: ClassifierConfig) -> list[ClassifiedItem]:
    # Returns successes only. Failures written to data/logs/{run_id}_failures.jsonl
    # as ClassificationFailure objects and counted in RunLog.error_count.
    results = []
    for item in items:
        try:
            ci = _classify_one(item, config)
            results.append(ci)
        except ClassificationError as e:
            _log_failure(ClassificationFailure(...))
    return results
```

**Prompt structure:** (Full prompt in references/prompting-guide.md)
- System prompt: role definition, constraints, output format
- User prompt: item fields (source, region, title, body excerpt) + expected JSON schema

**Model:** Default model configured via `classifier.model` in config. Initial suggested model: Claude Sonnet. Chosen for balanced latency, cost, and structured output quality. Verify model availability before implementation.

**Rules:**
1. One item per LLM call — don't batch (keeps output reliable and individually debuggable)
2. Validate JSON output with a schema validator — if parsing fails, retry up to `max_retries`, then create a `ClassificationFailure` and skip the item
3. Confidence is the LLM's self-assessment, not truth — never treat it as verification
4. Truncate body to `max_body_chars` (default: 2000) before sending to the LLM
5. Store both `evidence_quote` and `inference_note` — downstream consumers need to know what's source fact vs CSC interpretation
6. Log every classification: item ID, model used, tokens consumed, latency, parse success
7. Pass `duplicate_count` and `duplicate_source_names` to the prompt — multi-source signals deserve different framing than single-source items

**Human review flag triggers:**
- Regulatory, legal, compliance, lending, privacy, or customer harm implications
- High commercial impact but `duplicate_count == 0` (single source only)
- Low classifier confidence (below `confidence_floor`, default: 0.5)
- The `inference_note` is substantial (major leap from evidence to implication)
- Signal could cause a team to change roadmap, risk appetite, pricing, or customer messaging

**Config needed:**
- `model`: Model string (default: `claude-sonnet-4-20250514`)
- `max_body_chars`: Body truncation limit (default: 2000)
- `confidence_floor`: Below this, always flag for human review (default: 0.5)
- `max_retries`: JSON parse retry count (default: 1)

**Day 2 upgrade:** Becomes the Verification agent — cross-checks multiple sources for the same event, detects contradictions, routes low-confidence items to human review with suggested questions, and can request additional source fetches.

---

## Module 6: Signal scorer

**Job:** Apply a rule-based scoring formula to rank classified items by strategic importance.

No LLM here. The scoring formula is transparent, auditable, and adjustable via config. This keeps the "why is this ranked #1?" question always answerable.

**Scoring formula:**
```
strategic_score =
  0.30 × relevance_score +
  0.25 × impact_score +
  0.20 × urgency_score +
  0.15 × novelty_score +
  0.10 × source_weight −
  confidence_penalty
```

Where:
- `source_weight` is assigned per source in config (e.g. regulator=1.0, major news=0.75, aggregator=0.5)
- `confidence_penalty = max(0, 0.7 − confidence) × 0.25` — penalises items below 0.7 confidence, aligned with the human review threshold

The 0.7 threshold is intentional: it matches the classifier's `confidence_floor`-adjacent review trigger and ensures low-confidence items are visibly deprioritised in ranking, not just flagged.

**Implementation:**
```python
def score_items(items: list[ClassifiedItem], config: ScorerConfig) -> list[ScoredItem]:
    scored = []
    for item in items:
        source_weight = config.source_weights.get(item.source_name, 0.5)
        penalty = max(0, 0.7 - item.confidence) * 0.25
        score = (
            0.30 * item.relevance_score +
            0.25 * item.impact_score +
            0.20 * item.urgency_score +
            0.15 * item.novelty_score +
            0.10 * source_weight -
            penalty
        )
        breakdown = {
            "relevance": 0.30 * item.relevance_score,
            "impact": 0.25 * item.impact_score,
            "urgency": 0.20 * item.urgency_score,
            "novelty": 0.15 * item.novelty_score,
            "source_weight": 0.10 * source_weight,
            "confidence_penalty": penalty
        }
        scored.append(ScoredItem(**vars(item), strategic_score=score, score_breakdown=breakdown, rank=None))
    scored.sort(key=lambda x: x.strategic_score, reverse=True)
    for i, item in enumerate(scored):
        item.rank = i + 1
    return scored
```

**Rules:**
1. Keep weights in config — never hardcode in module logic
2. Store full `score_breakdown` dict for every item so ranking is auditable
3. Sort descending by `strategic_score` and assign rank
4. Source weights must be explicitly configured per source — default to 0.5 for unknown sources
5. Log the score distribution: min, max, mean, median for the batch

**Config needed:**
```yaml
scorer:
  weights:
    relevance: 0.30
    impact: 0.25
    urgency: 0.20
    novelty: 0.15
    source_weight: 0.10
  confidence_penalty_threshold: 0.7
  confidence_penalty_factor: 0.25
  source_weights:
    "ASIC Media": 1.0
    "ACCC": 1.0
    "Google News AU": 0.5
    "default": 0.5
```

**Day 2 upgrade:** Becomes the Strategic implication agent — converts scored signals into actionable implications (e.g. "If this regulation passes, our loan approval flow needs X change"), generates customer behaviour hypotheses, and manages a persistent watchlist.

---

## Module 7: LLM summariser

**Job:** Takes the top-ranked scored items and writes a decision-ready intelligence brief.

This is what stakeholders actually read. The brief needs to be concise, actionable, and honest about uncertainty. It follows a fixed template so readers always know where to look.

**Brief template:**
```markdown
# Chief Signal Cat Brief — {date_range}

## One-line readout
{The most important strategic interpretation in one sentence.}

## Top signals
1. **{Signal title}** — {what happened, one sentence}.
   **Fact:** {what the source explicitly says — no inference}.
   **Implication:** {what this may mean for product, design, risk, lending, or business}.
   **Assumption:** {what must be true for this implication to matter}.
   **Evidence:** {source name}, {publish date}, {URL}.
   **Confidence:** {High/Medium/Low} — {brief reason, e.g. "single official source" or "inferred from trend, not stated"}.
   **Human review:** {Yes — {reason} | No}.

## Watch item
{One thing to monitor next cycle and why. Forward-looking only — not a recap.}

## Human review flags
{Items that should not be treated as final intelligence without human review. If none: "None this cycle."}
```

The **Fact / Implication / Assumption** structure is mandatory. It prevents the classic LLM failure mode of turning a small article into a large strategic claim. The `Assumption` field forces the writer to make uncertainty visible rather than hide it in confident-sounding prose.

**Prompt structure:** (Full prompt in references/prompting-guide.md)
- System prompt: role, audience, tone constraints, template enforcement
- User prompt: date range, audience, formatted scored items (including `duplicate_count`, `evidence_quote`, `inference_note`), template

**Model:** Default configured via `summariser.model` in config. Initial suggested model: Claude Sonnet.

**Rules:**
1. Use the standard brief template — don't improvise structure
2. Every claim in Fact must trace back to the source — no inference allowed in that field
3. Implication and Assumption are CSC's interpretation — label them as such
4. Don't remove uncertainty to make the brief sound cleaner
5. Keep to top 3–5 signals — more dilutes attention
6. Items with `human_review_flag = true` go in the "Human review flags" section
7. The watch item must be forward-looking: what to look for next cycle, not a recap
8. Add a per-signal character cap in the prompt (suggested: ~400 chars per signal block) to keep briefs scannable

**Config needed:**
- `model`: Model string
- `top_n`: How many scored items to include (default: 5)
- `audience`: Who reads this (default: "product, design, and consumer finance stakeholders")
- `max_output_tokens`: Brief length cap (default: 2000)

**Day 2 upgrade:** Part of the Presentation agent — generates different formats (email brief, Slack summary, dashboard cards, API response) from the same intelligence. Can tailor depth and emphasis by audience.

---

## Module 8: Email output

**Job:** Deliver the brief to configured recipients.

**Day 1 approach:** Plain text email via SMTP or SendGrid. HTML is a fast-follow, not a Day 1 requirement.

**Email structure:**
- **Subject:** `[CSC] Brief — {date_range} — {one_line_readout_truncated}`
- **Body:** The markdown brief rendered as plain text
- **Footer:** Run timestamp, run ID, items processed/filtered/classified/scored, pipeline version

**Rules:**
1. Plain text first — works everywhere, easy to debug
2. Include source links as full URLs (not hyperlinks) for plain text compatibility
3. Add a pipeline stats footer so recipients know the system is working
4. Log: sent timestamp, recipients, subject line, delivery status, message ID
5. On send failure, retry once then log the error — don't block the pipeline

**Config needed:**
```yaml
email:
  provider: "smtp"  # or "sendgrid"
  smtp_host: "smtp.example.com"
  smtp_port: 587
  from_address: "signal-cat@example.com"
  recipients:
    - "product-team@example.com"
  alert_address: "alerts@example.com"
```

**Day 2 upgrade:** Part of the Presentation agent — adds Slack messages, dashboard views (web UI), and an API endpoint for programmatic access. Routing logic decides which channel based on signal urgency and audience.

---

## Cross-cutting concerns

### Append-only signal log

Every stage appends to a shared log. This is your audit trail and your future evaluation dataset.

| What to log | When |
|---|---|
| Raw items fetched | After source connector |
| Items dropped with reason | After filter rules |
| Items merged with reason | After deduplication |
| Classification results (full JSON) | After LLM classifier |
| Score breakdowns | After signal scorer |
| Brief text | After LLM summariser |
| Email delivery status | After email output |

Day 1 implementation: append to a JSONL file per run. Day 2: migrate to a proper signal store (SQLite or Postgres).

### Error handling philosophy

Not all errors are equal. Distinguish recoverable from fatal before writing any error handling code.

**Fatal errors — stop the run immediately:**

| Error | Why fatal |
|---|---|
| Config file missing or invalid YAML | Pipeline has no valid parameters to operate on |
| Required env var missing (e.g. `ANTHROPIC_API_KEY`) | No LLM calls possible |
| Schema validation broken (dataclass mismatch) | Data contract is broken; outputs are untrustworthy |
| Storage unavailable at run start | Can't write audit log; run is unverifiable |
| Scoring weights don't sum correctly | Ranking results would be wrong |

For fatal errors: log the error with full context, send an alert to `alert_address`, and exit. Do not produce a partial brief.

**Recoverable errors — log and continue:**

| Error | Behaviour |
|---|---|
| One source fetch fails | Log error, skip source, continue with others |
| One item fails classification (after retries) | Create `ClassificationFailure`, continue |
| Email send fails | Retry once, log if still failing, do not crash |
| One item has missing `published_at` | Apply `missing_published_at_policy`, continue |
| Fuzzy dedup comparison error | Log and keep both items |

For recoverable errors: the pattern is try → retry once with short delay → log with full context → continue. Count all errors in `RunLog.error_count`.

A run that classifies 40 of 50 items and logs 10 recoverable failures is valid. A run built on an invalid config is not — don't produce output from a broken foundation.

### Config management

All config lives in a single YAML file (or a small set of them). Never hardcode thresholds, model names, source URLs, API keys, email addresses, or scoring weights in module code.

Structure:
```yaml
# config.yaml
pipeline:
  synthesis_window_days: 3
  schedule_cron: "0 7 * * *"

sources:
  - name: "ASIC Media"
    type: "regulator"
    trust_tier: "official"
    url: "https://asic.gov.au/about-asic/news-centre/rss-feed/"
    region: "AU"
    source_weight: 1.0
    max_items: 20
  - name: "Google News AU"
    type: "news"
    trust_tier: "aggregator"
    url: "..."
    region: "AU"
    source_weight: 0.5
    max_items: 50

filter_rules:
  target_regions: ["AU"]
  max_age_days: 7
  domain_allowlist: []
  require_keyword_match: true
  min_keyword_matches: 1
  keyword_match_exempt_tiers: ["official"]
  missing_published_at_policy:
    official: "keep_with_warning"
    regulator: "keep_with_warning"
    news: "drop"
    aggregator: "drop"
    social: "drop"
    manual: "keep_with_warning"
  keyword_blocklist: [...]
  keyword_allowlist: [...]

classifier:
  model: "claude-sonnet-4-20250514"
  max_body_chars: 2000
  confidence_floor: 0.5
  max_retries: 1

scorer:
  weights: { relevance: 0.30, impact: 0.25, urgency: 0.20, novelty: 0.15, source_weight: 0.10 }
  confidence_penalty_threshold: 0.7
  confidence_penalty_factor: 0.25
  source_weights: { "ASIC Media": 1.0, "ACCC": 1.0, "Google News AU": 0.5, "default": 0.5 }

summariser:
  model: "claude-sonnet-4-20250514"
  top_n: 5
  audience: "product, design, and consumer finance stakeholders"
  max_output_tokens: 2000

email:
  provider: "smtp"
  recipients: [...]
  alert_address: "alerts@example.com"
```

### Testing strategy

Each module is a function that takes typed input and returns typed output. Test them with fixture data:

1. **Source connector:** Mock the HTTP response, verify RawItem output shape
2. **Filter rules:** Pass in known items, verify correct items are kept/dropped with right reasons
3. **Deduplicate:** Pass in items with duplicate URLs and similar titles, verify merging
4. **LLM classifier:** Mock the Anthropic API response, verify ClassifiedItem parsing and validation
5. **Signal scorer:** Pass in ClassifiedItems with known scores, verify ranking and breakdown
6. **LLM summariser:** Mock the API, verify brief follows template structure
7. **Email output:** Mock SMTP, verify email is sent with correct subject and body
8. **Integration:** Run the full pipeline with fixture data end to end

---

## Day 2 readiness checklist

Before moving to Day 2, Day 1 should satisfy all of these:

- [ ] Pipeline runs daily without manual intervention
- [ ] At least 3 cycles of briefs have been produced and reviewed by a human
- [ ] Scoring weights have been tuned at least once based on feedback
- [ ] The append-only log contains enough data to evaluate classifier accuracy
- [ ] At least one human review flag has been correctly triggered
- [ ] Config changes don't require code changes
- [ ] Every module can be called independently with test fixtures

---

## What to build first

Recommended build order:

1. **Data schemas** — define the dataclasses. Everything else depends on these.
2. **Source connector** — get real data flowing. Even a hardcoded RSS URL is fine to start.
3. **Filter rules** — reduce the noise so you can see signal quality.
4. **Deduplicate** — clean the data before spending LLM tokens.
5. **LLM classifier** — the most complex module. Get this working with a few test items.
6. **Signal scorer** — quick to implement once the classifier output shape is solid.
7. **LLM summariser** — produces the visible output. Tune the prompt iteratively.
8. **Email output** — the delivery mechanism. Can be a simple print-to-console first.
9. **Scheduler** — automate what already works manually.

Start with steps 1–4, then 5 with manual testing, then assemble the rest.
